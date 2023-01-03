import abc
import argparse
import shutil
import pathlib as pl
import hashlib
from typing import List, Union, Dict, Type


from agent_build_refactored.tools.steps_libs.utils import calculate_files_checksum
from agent_build_refactored.tools.steps_libs.subprocess_with_log import check_call_with_log
from agent_build_refactored.tools.constants import IN_DOCKER, SOURCE_ROOT, AGENT_SUBDIR_NAME, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT, Architecture
from agent_build_refactored.tools.runner import Runner, EnvironmentRunnerStep, ArtifactRunnerStep, DockerImageSpec, GitHubActionsSettings, RunnerStep, RunnerMappedPath

from agent_build_refactored.managed_packages.scalyr_agent_python3 import BUILD_EMBEDDED_PYTHON_STEPS, PREPARE_TOOLSET_STEPS, INSTALL_BUILD_DEPENDENCIES_STEPS, BUILD_AGENT_DEV_REQUIREMENTS_STEPS


BUILD_AGENT_WHEELS_SYSTEM_PYTHON_PY36 = ArtifactRunnerStep(
    name="build_agent_wheels_system_python_py36",
    script_path="agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/build_steps/build_wheels.sh",
    tracked_files_globs=[
        "agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/build_steps/pysnmp_setup.patch"
    ],
    base=DockerImageSpec(
        name="python:3.6",
        platform=Architecture.X86_64.as_docker_platform.value
    ),
    environment_variables={
        "SUBDIR_NAME": AGENT_SUBDIR_NAME,
        "REQUIREMENTS": REQUIREMENTS_COMMON,
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)

BUILD_AGENT_WHEELS_SYSTEM_PYTHON = ArtifactRunnerStep(
    name="build_agent_wheels_system_python",
    script_path="agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/build_steps/build_wheels.sh",
    tracked_files_globs=[
        "agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/build_steps/pysnmp_setup.patch"
    ],
    base=PREPARE_TOOLSET_STEPS[Architecture.X86_64],
    required_steps={
         "BUILD_SYSTEM_PYTHON_WHEELS_PY36": BUILD_AGENT_WHEELS_SYSTEM_PYTHON_PY36
    },
    environment_variables={
        "SUBDIR_NAME": AGENT_SUBDIR_NAME,
        "REQUIREMENTS_COMMON": REQUIREMENTS_COMMON,
        "PLATFORM_DEPENDENT_REQUIREMENTS": REQUIREMENTS_COMMON_PLATFORM_DEPENDENT,
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)



def create_build_agent_wheels_embedded_python(
        architecture: Architecture,
):
     return ArtifactRunnerStep(
        name=f"build_agent_wheels_embedded_python_{architecture.value}",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_wheels/embedded_python/build_steps/build_wheels.sh",
        base=PREPARE_TOOLSET_STEPS[architecture],
        required_steps={
            "BUILD_AGENT_DEV_REQUIREMENTS": BUILD_AGENT_DEV_REQUIREMENTS_STEPS[architecture]
        },
        environment_variables={
            "SUBDIR_NAME": AGENT_SUBDIR_NAME,
            "REQUIREMENTS_COMMON": REQUIREMENTS_COMMON,
            "REQUIREMENTS_COMMON_PLATFORM_DEPENDENT": REQUIREMENTS_COMMON_PLATFORM_DEPENDENT,
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
        )
    )


BUILD_AGENT_WHEELS_EMBEDDED_PYTHON = {
    Architecture.X86_64: create_build_agent_wheels_embedded_python(
        architecture=Architecture.X86_64,
    ),
    Architecture.ARM64: create_build_agent_wheels_embedded_python(
        architecture=Architecture.ARM64,
    )
}


def create_agent_wheels_package_root_step(
        architecture: Architecture = None
):

    if architecture is not None:
        build_wheels_step = BUILD_AGENT_WHEELS_EMBEDDED_PYTHON[architecture]
        name = "create_agent_wheels_embedded_python_package_root"
        venv_python3_executable_path = "agent_build_refactored/managed_packages/scalyr_agent_wheels/embedded_python/files/scalyr-agent-python3"
    else:
        build_wheels_step = BUILD_AGENT_WHEELS_SYSTEM_PYTHON
        name = "create_agent_wheels_system_python_package_root"
        venv_python3_executable_path = "agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/files/scalyr-agent-python3"

    return ArtifactRunnerStep(
        name=name,
        script_path="agent_build_refactored/managed_packages/scalyr_agent_wheels/build_steps/build_packages_roots.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/scalyr_agent_wheels/files/config/config.ini",
            "agent_build_refactored/managed_packages/scalyr_agent_wheels/files/scalyr-agent-2-requirements.py",
            "agent_build_refactored/managed_packages/scalyr_agent_wheels/files/config/additional-requirements.txt",
            "agent_build_refactored/managed_packages/scalyr_agent_wheels/install_scriptlets/system-python-postinstall.sh",
            venv_python3_executable_path,

        ],
        base=PREPARE_TOOLSET_STEPS[Architecture.X86_64],
        required_steps={
            "BUILD_WHEELS": build_wheels_step
        },
        environment_variables={
            "SUBDIR_NAME": AGENT_SUBDIR_NAME,
            "VENV_PYTHON3_EXECUTABLE_PATH": venv_python3_executable_path
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
        )
    )


CREATE_AGENT_WHEELS_EMBEDDED_PYTHON_PACKAGE_ROOT_STEPS = {
    Architecture.X86_64: create_agent_wheels_package_root_step(
        architecture=Architecture.X86_64
    ),
    Architecture.ARM64: create_agent_wheels_package_root_step(
        architecture=Architecture.ARM64
    )
}

CREATE_AGENT_WHEELS_SYSTEM_PYTHON_PACKAGE_ROOT_STEP = create_agent_wheels_package_root_step()