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


# Import modules that define any runner that is used during the builds.
# It is important to import them before the import of the 'ALL_RUNNERS' or otherwise, runners from missing mudules
# won't be presented in the "ALL_RUNNERS" final collection.
import tests.end_to_end_tests  # NOQA
import tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner # NOQA
import tests.end_to_end_tests.managed_packages_tests.conftest  # NOQA

# Import ALL_RUNNERS global collection only after all modules that define any runner are imported.
from agent_build_refactored.tools.runner import ALL_RUNNERS

from agent_build_refactored.tools.runner import Runner, RunnerStep, group_steps_by_stages, remove_steps_from_stages, sort_and_filter_steps

# Suffix that is appended to all steps cache keys. CI/CD cache can be easily invalidated by changing this value.
CACHE_VERSION_SUFFIX = "v14"


def get_all_used_steps() -> List[RunnerStep]:
    """
    Get list of all steps that are used in the whole project.
    """
    all_steps = []
    for runner_cls in ALL_RUNNERS:
        for step in runner_cls.get_all_steps(recursive=True):
            all_steps.append(step)

    return sort_and_filter_steps(steps=all_steps)


all_used_steps: Dict[str, RunnerStep] = {step.id: step for step in get_all_used_steps()}


step_stages = group_steps_by_stages(steps=list(all_used_steps.values()))


class CacheableStepRunner(Runner):
    """
    A "wrapper" runner class that is needed to locate and run cacheable steps.
    """
    STEP: RunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        return [cls.STEP]

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(CacheableStepRunner, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command")

        subparsers.add_parser("run-cacheable-step")

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(CacheableStepRunner, cls).handle_command_line_arguments(args=args)

        if args.command == "run-cacheable-step":
            cls._run_steps(
                steps=[cls.STEP],
                work_dir=pl.Path(args.work_dir)
            )
            exit(0)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)


def get_steps_runners():
    result_runners = {}

    for stage in step_stages:
        for step_id, step in stage.items():
            _RunnerCls = result_runners.get(step.id)
            if _RunnerCls is None:
                class _RunnerCls(CacheableStepRunner):
                    STEP = step
                    CLASS_NAME_ALIAS = f"{step_id}_cached"

                result_runners[step_id] = _RunnerCls

    return result_runners


steps_runners = get_steps_runners()


def get_missing_caches_matrices(existing_result_steps_ids_file: pl.Path):
    """
    Create GitHub Actions job matrix for each stage of steps.
    :param steps_with_existing_results_file:
    :return:
    """
    json_content = existing_result_steps_ids_file.read_text()
    existing_result_steps_ids = json.loads(json_content)

    filtered_stages = remove_steps_from_stages(
        stages=step_stages, steps_to_remove=existing_result_steps_ids
    )

    result_matrices = []
    for stage in filtered_stages:
        matrix_include = []

        for step_id, step in stage.items():

            required_steps_ids = []
            for req_step in step.get_all_required_steps():
                required_steps_ids.append(req_step.id)

            runner_cls = steps_runners[step_id]

            matrix_include.append(
                {
                    "step_runner_fqdn": runner_cls.FULLY_QUALIFIED_NAME,
                    "step_id": step.id,
                    "name": step.name,
                    "required_steps": sorted(required_steps_ids),
                    "cache_version_suffix": CACHE_VERSION_SUFFIX,
                }
            )

        matrix = {"include": matrix_include}
        result_matrices.append(matrix)

    return result_matrices


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
            stage_run_pre_built_job[
                "if"
            ] = f"${{{{ always() && (needs.{previous_run_pre_built_job_object_name}.result == 'success' || needs.{previous_run_pre_built_job_object_name}.result == 'skipped') && needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"
        else:
            stage_run_pre_built_job[
                "if"
            ] = f"${{{{ needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"

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

    all_cache_keys_parser = subparsers.add_parser("get-all-steps-ids")

    get_cache_version_suffix_parser = subparsers.add_parser("get-cache-version-suffix")

    update_files_parser = subparsers.add_parser("update-files")

    args = parser.parse_args()

    if args.command == "get-missing-caches-matrices":
        matrices = get_missing_caches_matrices(
            existing_result_steps_ids_file=pl.Path(args.existing_result_steps_ids_file),
        )
        print(json.dumps(matrices))
    elif args.command == "get-all-steps-ids":
        print(json.dumps(list(sorted(all_used_steps.keys()))))

    elif args.command == "update-files":
        update_files()
    elif args.command == "get-cache-version-suffix":
        print(CACHE_VERSION_SUFFIX)

    exit(0)


