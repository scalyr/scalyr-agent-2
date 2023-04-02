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
This script reads job matrices of the CI/CD workflow and searches for
cacheable runner steps that should be executed in a separate Ci/CD job to parallelize
builds.
"""

import argparse
import collections
import copy
import json
import os
import pathlib as pl
import sys
import strictyaml
import logging
from typing import Dict, List

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
import requests

logging.basicConfig(
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent

sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.runner import Runner, RunnerStep, RunnerMeta

from agent_build_refactored.cicd.tttt import ALL_RUNNERS


CACHE_VERSION_SUFFIX = "v12"

used_builders = []

existing_runners = {}
builders_to_prebuilt_runners = {}

all_used_steps: Dict[str, RunnerStep] = {}
for runner_cls in ALL_RUNNERS:
    for step_id, step in runner_cls.get_all_steps(recursive=True).items():
        all_used_steps[step_id] = step

a=10

def create_wrapper_runner_from_step(step: RunnerStep):
    class StepWrapperRunner(Runner):
        CLASS_NAME_ALIAS = f"{step_id}_pre_build"

        @classmethod
        def get_all_required_steps(cls) -> List[RunnerStep]:
            return [step]

    return StepWrapperRunner


def get_steps_levels():
    global all_used_steps

    remaining_steps = all_used_steps.copy()
    levels = []

    while remaining_steps:
        current_layer = {}
        for step_id, step in remaining_steps.items():
            add = True

            for req_step_id, req_step in step.get_all_required_steps().items():
                if req_step_id in remaining_steps:
                    add = False
                    break

            if add:
                current_layer[step_id] = step

        for step_id, step in current_layer.items():
            remaining_steps.pop(step_id)
        levels.append(current_layer)

    return levels


levels = get_steps_levels()

runner_levels = []
for level_steps in levels:
    current_runner_level = {}
    for step_id, step in level_steps.items():
        runner_cls = existing_runners.get(step.id)
        if runner_cls is None:
            runner_cls = create_wrapper_runner_from_step(step)
            existing_runners[step.id] = runner_cls

        fqdn = runner_cls.FULLY_QUALIFIED_NAME
        current_runner_level[fqdn] = {
            "step": step,
            "runner": runner_cls
        }

    runner_levels.append(current_runner_level)


def get_missing_caches_matrices(input_missing_cache_keys_file: pl.Path):
    json_content = input_missing_cache_keys_file.read_text()
    missing_cache_keys = json.loads(json_content)

    logger.info("MISSING")
    logger.info(missing_cache_keys)

    matrices = []
    for level in runner_levels:
        matrix_include = []

        for step_wrapper_runner_fqdn, info in level.items():

            step = info["step"]
            step_id = step.id
            logger.info(f"STEP: {step_id}")
            if step_id not in missing_cache_keys:
                logger.info("SKIP")
                continue

            logger.info("CONTINUE")
            required_steps_ids = []
            for req_step_id in step.get_all_required_steps().keys():
                required_steps_ids.append(req_step_id)

            matrix_include.append({
                "step_runner_fqdn": step_wrapper_runner_fqdn,
                "step_id": step_id,
                "name":  info["step"].name,
                "required_steps": sorted(required_steps_ids),
                "cache_version_suffix": CACHE_VERSION_SUFFIX,
            })

        if len(matrix_include) > 0:
            matrix = {
                "include": matrix_include
            }
        else:
            matrix = ""

        matrix = {
            "include": matrix_include
        }
        matrices.append(matrix)

    return matrices


def render_workflow_yaml():
    template_path = pl.Path(__file__).parent / "run-pre-build-jobs_template.yml"
    template_ymp = strictyaml.load(template_path.read_text())
    workflow = template_ymp.data

    jobs = workflow["jobs"]

    pre_job = jobs["pre_job"]

    all_used_steps_ids = list(sorted(all_used_steps.keys()))
    # pre_job_outputs["all_steps_ids_json"] = json.dumps(all_used_steps_ids)
    # pre_job_outputs["cache_version_suffix"] = CACHE_VERSION_SUFFIX

    pre_job_steps = pre_job["steps"]

    get_missing_cache_steps = {
        "name": "Get missing step caches matrices",
        "id": "get_missing_caches_matrices",
        "uses": "./.github/actions/get_steps_missing_caches",
        "with": {
            "steps_ids": json.dumps(all_used_steps_ids),
            "cache_version_suffix": CACHE_VERSION_SUFFIX,
            "cache_root": "agent_build_output/step_cache",
            "lookup_only": "true",
        }
    }

    pre_job_steps.insert(2, get_missing_cache_steps)

    run_pre_built_job_object_name = "run_pre_built_job"
    run_pre_built_job = jobs.pop(run_pre_built_job_object_name)

    pre_job_outputs = {}
    counter = 0
    for level in runner_levels:
        level_run_pre_built_job = copy.deepcopy(run_pre_built_job)
        if counter > 0:
            previous_run_pre_built_job_object_name = f"{run_pre_built_job_object_name}{counter - 1}"
            level_run_pre_built_job["needs"].append(previous_run_pre_built_job_object_name)
            level_run_pre_built_job["if"] = f"${{{{ always() && (needs.{previous_run_pre_built_job_object_name}.result == 'success' || needs.{previous_run_pre_built_job_object_name}.result == 'skipped') && needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"
        else:
            level_run_pre_built_job["if"] = f"${{{{ needs.pre_job.outputs.matrix_length{counter} != '0' }}}}"

        level_run_pre_built_job["name"] = f"Level {counter} ${{{{ matrix.name }}}}'"
        level_run_pre_built_job["strategy"]["matrix"] = f"${{{{ fromJSON(needs.pre_job.outputs.matrix{counter}) }}}}"

        pre_job_outputs[f"matrix{counter}"] = f"${{{{ steps.print.outputs.matrix{counter} }}}}"
        pre_job_outputs[f"matrix_length{counter}"] = f"${{{{ steps.print.outputs.matrix_length{counter} }}}}"

        level_run_pre_built_job_object_name = f"{run_pre_built_job_object_name}{counter}"
        jobs[level_run_pre_built_job_object_name] = level_run_pre_built_job
        counter += 1

    pre_job["outputs"] = pre_job_outputs

    workflow_path = SOURCE_ROOT / ".github/workflows/run-pre-build-jobs.yml"

    workflow_path.write_text(
        strictyaml.as_document(workflow).as_yaml()
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    missing_caches_matrices_parser = subparsers.add_parser("get-missing-caches-matrices")
    missing_caches_matrices_parser.add_argument(
        "--input-missing-cache-keys-file",
        required=True
    )

    all_cache_keys_parser = subparsers.add_parser("all-cache-keys")

    get_cache_version_suffix_parser = subparsers.add_parser("get-cache-version-suffix")

    render_workflow_yaml_parser = subparsers.add_parser("render-workflow-yaml")

    args = parser.parse_args()

    if args.command == "get-missing-caches-matrices":
        matrices = get_missing_caches_matrices(
            input_missing_cache_keys_file=pl.Path(args.input_missing_cache_keys_file),
        )
        print(json.dumps(matrices))
    elif args.command == "render-workflow-yaml":
        render_workflow_yaml()
    elif args.command == "get-cache-version-suffix":
        print(CACHE_VERSION_SUFFIX)


    exit(0)


