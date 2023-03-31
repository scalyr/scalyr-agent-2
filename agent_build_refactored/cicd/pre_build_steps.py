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

import argparse
import collections
import json
import os
import pathlib as pl
import sys
from typing import Dict

from agent_build_refactored.tools.runner import Runner, RunnerStep

from agent_build_refactored import ALL_USED_BUILDERS


used_builders = []

existing_runners = {}
builders_to_prebuilt_runners = {}


all_used_steps: Dict[str, RunnerStep] = {}
for name, runner_cls in ALL_USED_BUILDERS.items():
    for step_id, step in runner_cls.get_all_steps().items():
        all_used_steps[step_id] = step


def get_layers():
    global all_used_steps

    remaining_steps = all_used_steps.copy()
    layers = []

    while remaining_steps:
        current_layer = {}
        for step_id, step in remaining_steps.items():
            add = True

            if step_id == 'build_python_3_x86_64-centos-6-linux-amd64-64845615694c294080e6a712af1edc7c0bd92841cf8887638a81662ca90daa54':
                a=10
            for req_step_id, req_step in step.get_all_required_steps().items():
                if req_step_id in remaining_steps:
                    add = False
                    break

            if add:
                current_layer[step_id] = step

        for step_id, step in current_layer.items():
            remaining_steps.pop(step_id)
        layers.append(current_layer)

    return layers

l = get_layers()
a=10



for step_id, step in pre_built_steps.items():
    StepWrapperRunner = existing_runners.get(step.id)
    if StepWrapperRunner is None:
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
        existing_runners[step.id] = StepWrapperRunner

    fqdn = StepWrapperRunner.get_fully_qualified_name()
    builders_to_prebuilt_runners[fqdn] = StepWrapperRunner


if __name__ == "__main__":
    pass
