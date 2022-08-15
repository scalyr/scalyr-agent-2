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
This script gathers all cacheable runner steps that are set to be pre-built in a separate GitHub Actions job.
"""

import json

from agent_build.tools.runner import Runner
from agent_build.docker_image_builders import ALL_DOCKER_IMAGE_BUILDERS, , K8S_DEFAULT_BUILDERS

ALL_RUNNERS = [*list(DOCKER_IMAGE_BUILDERS.values())]

ALL_STEPS_TO_PREBUILD = {}
# Search for all runer steps that has to be pre-built.
for runner in ALL_RUNNERS:
    for cacheable_step in runner.get_all_cacheable_steps():
        if not cacheable_step.github_actions_settings.pre_build_in_separate_job:
            continue
        ALL_STEPS_TO_PREBUILD[cacheable_step.id] = cacheable_step

ALL_STEP_BUILDERS = []

# Create "dummy" Runner for each runner step that has to be pre-built, this dummy runner will be executed
# by its fqdn to run the step.
for step_id, step in ALL_STEPS_TO_PREBUILD.items():

    class StepWrapperRunner(Runner):
        REQUIRED_STEPS = [step]

    # Since this runner class is created dynamically we have to generate a constant fqdn for it.
    StepWrapperRunner.assign_fully_qualified_name(
        class_name=StepWrapperRunner.__name__,
        module_name=__name__,
        class_name_suffix=step.id,
    )
    ALL_STEP_BUILDERS.append(StepWrapperRunner)


if __name__ == "__main__":
    matrix = {"include": []}

    for builder in ALL_STEP_BUILDERS:
        matrix["include"].append(
            {
                "name": f"Pre-build: {builder.REQUIRED_STEPS[0].name}",
                "step-builder-fqdn": builder.get_fully_qualified_name(),
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))
