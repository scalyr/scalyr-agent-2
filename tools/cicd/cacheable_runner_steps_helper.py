# Copyright 2014-2022 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This script helps GitHub Actions CI/CD to get information about steps that can be run and cached in parallel jobs. That
has to decrease overall build time.

How it works:


"""

import argparse
import copy
import json
import pathlib as pl
import subprocess
import sys
import strictyaml
import logging
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.

SCRIPT_PATH = pl.Path(__file__).absolute()
SOURCE_ROOT = SCRIPT_PATH.parent.parent.parent
sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.runner import remove_steps_from_stages
from tools.cicd import step_stages, steps_runners, all_used_steps, CACHE_VERSION_SUFFIX


def get_missing_caches_matrices(existing_result_steps_ids_file: pl.Path, github_step_output_file: pl.Path):
    """
    Create GitHub Actions job matrix for each stage of steps.
    :param existing_result_steps_ids_file:
    :return:
    """
    json_content = existing_result_steps_ids_file.read_text()
    existing_result_steps_ids = json.loads(json_content)

    filtered_stages = remove_steps_from_stages(
        stages=step_stages, steps_to_remove=existing_result_steps_ids
    )

    stages = []
    last_non_empty_matrix_index = -1

    for i, stage in enumerate(filtered_stages):
        stage_jobs = []

        for step_id, step in stage.items():

            required_steps_ids = []
            for req_step in step.get_all_required_steps():
                required_steps_ids.append(req_step.id)

            runner_cls = steps_runners[step_id]

            stage_jobs.append(
                {
                    "step_runner_fqdn": runner_cls.FULLY_QUALIFIED_NAME,
                    "step_id": step.id,
                    "name": step.name,
                    "required_steps": sorted(required_steps_ids),
                    "cache_version_suffix": CACHE_VERSION_SUFFIX,
                }
            )

        if len(stage_jobs) > 0:
            last_non_empty_matrix_index = i

        stages.append(stage_jobs)

    with github_step_output_file.open("w") as f:
        for i, stage_jobs in enumerate(stages):

            add_skip_job = False
            if len(stage_jobs) == 0:
                if i <= last_non_empty_matrix_index:
                    add_skip_job = True

            if add_skip_job:
                stage_jobs.append({
                    "name": "dummy"
                })

            matrix = {"include": stage_jobs}

            f.write(f"stage_{i}_matrix={json.dumps(matrix)}\n")
            if len(stage_jobs) == 0:
                stage_skip = "true"
            else:
                stage_skip = "false"

            f.write(f"stage_{i}_skip={stage_skip}\n")


def generate_workflow_yaml():
    """
    This function generates yml file for workflow that run pre-built steps.

    """
    template_path = SCRIPT_PATH.parent / "reusable-run-cacheable-runner-steps-template.yml"
    template_ymp = strictyaml.load(template_path.read_text())
    workflow = template_ymp.data

    jobs = workflow["jobs"]

    run_pre_built_job_object_name = "run_pre_built_job"
    run_pre_built_job = jobs.pop(run_pre_built_job_object_name)

    pre_job_outputs = {}
    for counter in range(len(step_stages)):
        stage_run_pre_built_job = copy.deepcopy(run_pre_built_job)
        if counter > 0:
            previous_run_pre_built_job_object_name = (
                f"{run_pre_built_job_object_name}{counter - 1}"
            )
            stage_run_pre_built_job["needs"].append(
                previous_run_pre_built_job_object_name
            )
        #     stage_run_pre_built_job[
        #         "if"
        #     ] = f"${{{{ always() && (needs.{previous_run_pre_built_job_object_name}.result == 'success' || needs.{previous_run_pre_built_job_object_name}.result == 'skipped') && needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"
        # else:
        #
        #     stage_run_pre_built_job[
        #         "if"
        #     ] = f"${{{{ needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"

        stage_run_pre_built_job["name"] = f"{counter} ${{{{ matrix.name }}}}"
        stage_run_pre_built_job["strategy"][
            "matrix"
        ] = f"${{{{ fromJSON(needs.pre_job.outputs.matrix{counter}) }}}}"

        pre_job_outputs[
            f"matrix{counter}"
        ] = f"${{{{ steps.print_missing_caches_matrices.outputs.matrix{counter} }}}}"
        pre_job_outputs[
            f"matrix_length{counter}"
        ] = f"${{{{ steps.print_missing_caches_matrices.outputs.matrix_length{counter} }}}}"

        stage_run_pre_built_job_object_name = (
            f"{run_pre_built_job_object_name}{counter}"
        )
        jobs[stage_run_pre_built_job_object_name] = stage_run_pre_built_job

        for step in stage_run_pre_built_job["steps"]:
            step["if"] = "${{ matrix.name != 'dummy' }}"

    pre_job = jobs["pre_job"]
    pre_job["outputs"] = pre_job_outputs

    workflow_path = SOURCE_ROOT / ".github/workflows/reusable-run-cacheable-runner-steps.yml"

    yaml_content = strictyaml.as_document(workflow).as_yaml()

    # Add notification comment, that this YAML was auto-generated.

    script_rel_path = SCRIPT_PATH.relative_to(SOURCE_ROOT)
    template_rel_path = template_path.relative_to(SOURCE_ROOT)
    comment = f"# IMPORTANT: Do not modify.\n" \
              f"# This workflow file is generated by the script '{script_rel_path}' from the template '{template_rel_path}'.\n" \
              f"# Modify those files in order to make changes to the workflow."

    yaml_content = f"{comment}\n{yaml_content}"
    workflow_path.write_text(yaml_content)


def update_files():
    """

    :return:
    """
    generate_workflow_yaml()

    # Update the "restore_steps_caches" action source.
    action_root = SOURCE_ROOT / ".github/actions/restore_steps_caches"

    ncc_executable = action_root / "node_modules/.bin/ncc"

    subprocess.run(
        [
            ncc_executable,
            "build",
            "index.js",
        ],
        cwd=action_root,
        check=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    missing_caches_matrices_parser = subparsers.add_parser(
        "get-missing-caches-matrices"
    )
    missing_caches_matrices_parser.add_argument(
        "--existing-result-step-ids-file", required=True
    )
    missing_caches_matrices_parser.add_argument(
        "--github-step-output-file", required=True
    )

    all_cache_keys_parser = subparsers.add_parser("get-all-steps-ids")

    get_cache_version_suffix_parser = subparsers.add_parser("get-cache-version-suffix")

    update_files_parser = subparsers.add_parser("update-files")

    args = parser.parse_args()

    if args.command == "get-missing-caches-matrices":
        get_missing_caches_matrices(
            existing_result_steps_ids_file=pl.Path(args.existing_result_step_ids_file),
            github_step_output_file=pl.Path(args.github_step_output_file)
        )
    elif args.command == "get-all-steps-ids":
        print(json.dumps(list(sorted(all_used_steps.keys()))))

    elif args.command == "update-files":
        update_files()
    elif args.command == "get-cache-version-suffix":
        print(CACHE_VERSION_SUFFIX)

    exit(0)
