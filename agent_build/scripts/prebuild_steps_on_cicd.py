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

import json

from agent_build.tools.runner import Runner
from agent_build.docker_image_builders import DOCKER_IMAGE_BUILDERS


ALL_STEPS_TO_PREBUILD = {}

for builder in DOCKER_IMAGE_BUILDERS.values():
    for cacheable_step in builder.get_all_cacheable_steps():
        if not cacheable_step.pre_build_in_cdcd:
            continue
        ALL_STEPS_TO_PREBUILD[cacheable_step.id] = cacheable_step

ALL_STEP_BUILDERS = []
for step_id, step in ALL_STEPS_TO_PREBUILD.items():
    class StepWrapperRunner(Runner):
        REQUIRED_STEPS = [step]


    StepWrapperRunner.assign_fully_qualified_name(
        class_name=StepWrapperRunner.__name__,
        module_name=__name__,
        class_name_suffix=step.id,
    )
    ALL_STEP_BUILDERS.append(StepWrapperRunner)

if __name__ == '__main__':
    matrix = {
        "include": []
    }

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