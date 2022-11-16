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

import  pathlib as pl

from agent_build_refactored.tools.runner import EnvironmentRunnerStep, GitHubActionsSettings, DockerImageSpec, ArtifactRunnerStep
from agent_build_refactored.tools.constants import DockerPlatform, EMBEDDED_PYTHON_VERSION

PYTHON_PACKAGE_VERSION_PATH = pl.Path(__file__).parent / "PYTHON_PACKAGE_VERSION"
PYTHON_PACKAGE_VERSION = PYTHON_PACKAGE_VERSION_PATH.read_text().strip()

AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME = "scalyr-agent-2-dependencies"
PYTHON_PACKAGE_NAME = "scalyr-agent-python3"
PYTHON_PACKAGE_SSL_VERSION = "1.1.1k"
EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])

INSTALL_GCC_7_GLIBC_X86_64 = EnvironmentRunnerStep(
        name="install_gcc_7",
        script_path="agent_build_refactored/managed_packages/steps/install_gcc_7.sh",
        base=DockerImageSpec(
            name="centos:6",
            platform=DockerPlatform.AMD64.value
        ),
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


def create_build_dependencies_step(
        base_image: EnvironmentRunnerStep
):

    return EnvironmentRunnerStep(
        name="install_build_dependencies",
        script_path="agent_build_refactored/managed_packages/steps/install_build_dependencies.sh",
        base=base_image,
        environment_variables={
            "PERL_VERSION": "5.36.0",
            "ZX_VERSION": "5.2.6",
            "TEXTINFO_VERSION": "6.8",
            "M4_VERSION": "1.4.19",
            "LIBTOOL_VERSION": "2.4.6",
            "AUTOCONF_VERSION": "2.71",
            "AUTOMAKE_VERSION": "1.16",
            "HELP2MAN_VERSION": "1.49.2",
            "LZMA_VERSION": "4.32.7",
            "OPENSSL_VERSION": PYTHON_PACKAGE_SSL_VERSION,
            "LIBFFI_VERSION": "3.4.2",
            "UTIL_LINUX_VERSION": "2.38",
            "NCURSES_VERSION": "6.3",
            "LIBEDIT_VERSION": "20210910-3.1",
            "GDBM_VERSION": "1.23",
            "ZLIB_VERSION": "1.2.13",
            "BZIP_VERSION": "1.0.8",
            "RUST_VERSION": "1.63.0",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64 = create_build_dependencies_step(
    base_image=INSTALL_GCC_7_GLIBC_X86_64
)


def create_build_python_step(
        base_step: EnvironmentRunnerStep
):
    return ArtifactRunnerStep(
        name="build_python",
        script_path="agent_build_refactored/managed_packages/steps/build_python.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/files/scalyr-agent-2-python3",
        ],
        base=base_step,
        environment_variables={
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "PYTHON_INSTALL_PREFIX": "/usr",
            "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


BUILD_PYTHON_GLIBC_X86_64 = create_build_python_step(
    base_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64
)


def create_build_agent_libs_step(
        base_step: EnvironmentRunnerStep,
        build_python_step: ArtifactRunnerStep
):
    return ArtifactRunnerStep(
        name="build_agent_libs",
        script_path="agent_build_refactored/managed_packages/steps/build_agent_libs.sh",
        tracked_files_globs=[
            "agent_build/requirement-files/*.txt",
            "dev-requirements.txt"
        ],
        base=base_step,
        required_steps={
            "BUILD_PYTHON": build_python_step
        },
        environment_variables={
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


BUILD_AGENT_LIBS_GLIBC_X86_64 = create_build_agent_libs_step(
    base_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64,
    build_python_step=BUILD_PYTHON_GLIBC_X86_64
)


PREPARE_TOOLSET_GLIBC_X86_64 = EnvironmentRunnerStep(
    name="prepare_toolset",
    script_path="agent_build_refactored/managed_packages/steps/prepare_toolset.sh",
    tracked_files_globs=[
        "agent_build_refactored/tools/steps_libs/step_tools.py"
    ],
    base=DockerImageSpec(
        name="ubuntu:22.04",
        platform=DockerPlatform.AMD64.value
    ),
    required_steps={
        "BUILD_PYTHON": BUILD_PYTHON_GLIBC_X86_64,
        "BUILD_AGENT_LIBS": BUILD_AGENT_LIBS_GLIBC_X86_64
    },
    environment_variables={
        "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
        "FPM_VERSION": "1.14.2",
        "PACKAGECLOUD_VERSION": "0.3.11"
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)


def create_download_from_packageloud_step(
        name: str,
        package_name: str,
        package_version: str,
        package_type: str,
        package_architecture: str,
        user_name: str,
        repo_name: str
):

    package_filename = f"{package_name}_{package_version}_{package_architecture}.{package_type}"
    return ArtifactRunnerStep(
        name=name,
        script_path="agent_build_refactored/managed_packages/steps/download_package_from_packagecloud.py",
        tracked_files_globs=[
            "agent_build_refactored/tools/steps_libs/step_tools.py"
        ],
        base=PREPARE_TOOLSET_GLIBC_X86_64,
        environment_variables={
            "PACKAGE_FILENAME": package_filename,
            "USER_NAME": user_name,
            "REPO_NAME": repo_name
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


DOWNLOAD_PYTHON_PACKAGE_FROM_PACKAGECLOUD = create_download_from_packageloud_step(
    name="download_python_package_from_packagecloud",
    package_name=PYTHON_PACKAGE_NAME,
    package_version=PYTHON_PACKAGE_VERSION,
    package_type="deb",
    package_architecture="amd64",
    user_name="ArthurSentinelone",
    repo_name="DataSetAgent"
)