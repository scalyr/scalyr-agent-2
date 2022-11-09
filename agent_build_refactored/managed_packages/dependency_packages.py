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

from agent_build_refactored.tools.runner import EnvironmentRunnerStep, GitHubActionsSettings, DockerImageSpec, ArtifactRunnerStep
from agent_build_refactored.tools.constants import DockerPlatform, EMBEDDED_PYTHON_VERSION
from agent_build_refactored.tools.build_python.build_python import BUILD_PYTHON_GLIBC_X86_64 ,PREPARE_PYTHON_ENVIRONMENT_GLIBC_X64, EMBEDDED_PYTHON_SHORT_VERSION


PYTHON_DEPENDENCY_PACKAGE_NAME = "scalyr-agent-python3"

PREPARE_FPM_BUILDER = EnvironmentRunnerStep(
    name="prepare_fpm_builder",
    script_path="agent_build_refactored/managed_packages/steps/prepare_fpm_builder.sh",
    base=DockerImageSpec(
        name="ubuntu:22.04",
        platform=DockerPlatform.AMD64.value
    ),
    required_steps={
        "BUILD_PYTHON": BUILD_PYTHON_GLIBC_X86_64
    },
    environment_variables={
        "FPM_VERSION": "1.14.2"
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)


def create_build_python_package_step(
    build_python_step: ArtifactRunnerStep,
    package_architecture: str,
    package_type: str
):

    return ArtifactRunnerStep(
        name="build_python_package",
        script_path="agent_build_refactored/managed_packages/steps/build_python_package.py",
        base=PREPARE_FPM_BUILDER,
        tracked_files_globs=[
            "agent_build_refactored/tools/steps_libs/subprocess_with_log.py",
        ],
        required_steps={
            "BUILD_PYTHON": build_python_step
        },
        environment_variables={
            "PACKAGE_NAME":  PYTHON_DEPENDENCY_PACKAGE_NAME,
            "PACKAGE_ARCHITECTURE": package_architecture,
            "PACKAGE_TYPE": package_type,
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


def create_build_agent_python_dependencies_package_step(
        base_step: EnvironmentRunnerStep,
        build_python_package_step: ArtifactRunnerStep,
        package_architecture: str,
        package_type: str
):
    build_agent_python_dependencies = ArtifactRunnerStep(
        name="build_agent_python_dependencies",
        script_path="agent_build_refactored/managed_packages/steps/build_agent_python_dependencies.sh",
        tracked_files_globs=[
            "agent_build/requirement-files/main-requirements.txt",
            "agent_build/requirement-files/compression-requirements.txt",
        ],
        base=base_step,
        environment_variables={
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )

    return ArtifactRunnerStep(
        name="build_agent_python_dependencies_package",
        script_path="agent_build_refactored/managed_packages/steps/build_agent_python_dependencies_package.py",
        tracked_files_globs=[
            "agent_build_refactored/tools/steps_libs/subprocess_with_log.py",
        ],
        base=PREPARE_FPM_BUILDER,

        required_steps={
            "BUILD_PYTHON_PACKAGE": build_python_package_step,
            "BUILD_AGENT_PYTHON_DEPENDENCIES": build_agent_python_dependencies
        },
        environment_variables={
            "PACKAGE_NAME":  "scalyr-agent-dependencies",
            "PACKAGE_ARCHITECTURE": package_architecture,
            "PACKAGE_TYPE": package_type,
            "PYTHON_PACKAGE_NAME": PYTHON_DEPENDENCY_PACKAGE_NAME,
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


BUILD_PYTHON_PACKAGE_GLIBC_X86_64 = create_build_python_package_step(
    build_python_step=BUILD_PYTHON_GLIBC_X86_64,
    package_architecture="amd64",
    package_type="deb"
)

BUILD_AGENT_PYTHON_DEPENDENCIES_PACKAGE_GLIBC_X86_64 = create_build_agent_python_dependencies_package_step(
    base_step=PREPARE_PYTHON_ENVIRONMENT_GLIBC_X64,
    build_python_package_step=BUILD_PYTHON_PACKAGE_GLIBC_X86_64,
    package_architecture="amd64",
    package_type="deb"
)