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

from agent_build_refactored.tools.runner import (
    Runner,
    EnvironmentRunnerStep,
    GitHubActionsSettings,
)
from agent_build_refactored.tools.constants import AGENT_BUILD_PATH
from agent_build_refactored.docker_image_builders import ALL_IMAGE_BUILDERS
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_MANAGED_PACKAGE_BUILDERS,
)


# Step that runs small script which installs requirements for the test/dev environment.
INSTALL_TEST_REQUIREMENT_STEP = EnvironmentRunnerStep(
    name="install_test_requirements",
    script_path="agent_build_refactored/scripts/steps/deploy-test-environment.sh",
    tracked_files_globs=[AGENT_BUILD_PATH / "requirement-files/*.txt"],
    github_actions_settings=GitHubActionsSettings(cacheable=True),
)


class BuildTestEnvironment(Runner):
    BASE_ENVIRONMENT = INSTALL_TEST_REQUIREMENT_STEP


ALL_USED_BUILDERS = {**ALL_IMAGE_BUILDERS, **ALL_MANAGED_PACKAGE_BUILDERS}
