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
import json
import os
import pathlib as pl
import sys
from typing import Dict

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
import requests

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent

sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.runner import Runner, RunnerStep

from agent_build_refactored import ALL_USED_BUILDERS



used_builders = []

existing_runners = {}
builders_to_prebuilt_runners = {}

# pre_built_steps: Dict[str, RunnerStep] = {}
# for name, runner_cls in ALL_USED_BUILDERS.items():
#     for step in runner_cls.get_all_required_steps():
#         if not step.github_actions_settings.pre_build_in_separate_job:
#             continue
#
#         pre_built_steps[step.id] = step

all_used_steps: Dict[str, RunnerStep] = {}
for name, runner_cls in ALL_USED_BUILDERS.items():
    for step_id, step in runner_cls.get_all_steps().items():
        all_used_steps[step_id] = step


def create_wrapper_runner_from_step(step: RunnerStep):
    # Create "dummy" Runner for each runner step that has to be pre-built, this dummy runner will be executed
    # by its fqdn to run the step.
    class StepWrapperRunner(Runner):
        REQUIRED_STEPS = [step]

    # Since this runner class is created dynamically we have to generate a constant fqdn for it.
    StepWrapperRunner.assign_fully_qualified_name(
        class_name="pre-built-",
        module_name=__name__,
        class_name_suffix=step.id,
    )
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

        fqdn = runner_cls.get_fully_qualified_name()
        current_runner_level[fqdn] = {
            "step": step,
            "runner": runner_cls
        }

    runner_levels.append(current_runner_level)


def get_missing_caches_matrices(input_missing_cache_keys_file: pl.Path):
    json_content = input_missing_cache_keys_file.read_text()
    missing_cache_keys = json.loads(json_content)

    matrices = []
    for level in runner_levels:
        matrix_include = []

        for step_wrapper_runner_fqdn, info in level.items():

            if info["step"].id not in missing_cache_keys:
                continue

            matrix_include.append({
                "step_runner_fqdn": step_wrapper_runner_fqdn,
                "cache_key": info["step"].id,
                "name": step.name
            })

        matrix = {
            "include": matrix_include
        }
        matrices.append(matrix)

    return matrices


def get_all_cache_keys():
    result = set()
    for level in runner_levels:
        for info in level.values():
            result.add(info["step"].id)

    return json.dumps(list(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    missing_caches_matrices_parser = subparsers.add_parser("get-missing-caches-matrices")
    missing_caches_matrices_parser.add_argument(
        "--input-missing-cache-keys-file",
        required=True
    )

    all_cache_keys_parser = subparsers.add_parser("all-cache-keys")

    args = parser.parse_args()

    if args.command == "get-missing-caches-matrices":
        matrices = get_missing_caches_matrices(
            input_missing_cache_keys_file=pl.Path(args.input_missing_cache_keys_file),
        )
        print(json.dumps(matrices))
    elif args.command == "all-cache-keys":
        print(get_all_cache_keys())

    exit(0)
