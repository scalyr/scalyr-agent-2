# Copyright 2014-2023 Scalyr Inc.
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


import pathlib as pl

from agent_build_refactored.tools.constants import Architecture
from agent_build_refactored.tools.runner import RunnerStep, EnvironmentRunnerStep


def create_step(
        name_suffix: str,
        install_build_environment_step: EnvironmentRunnerStep,
        build_python_dependencies_step: RunnerStep,
        build_openssl_step: RunnerStep,
        build_python_step: RunnerStep,
        rust_version: str,
        python_install_prefix: str,
        run_in_remote_docker: bool = False
):
    architecture = install_build_environment_step.architecture
    if architecture == Architecture.X86_64:
        rust_target_platform = "x86_64-unknown-linux-gnu"
    elif architecture == Architecture.ARM64:
        rust_target_platform = "aarch64-unknown-linux-gnu"
    else:
        raise Exception(f"Unknown architecture '{architecture.value}'")

    return RunnerStep(
        name=f"build_dev_requirements_{name_suffix}",
        script_path=pl.Path(__file__).parent / "build_dev_requirements.sh",
        tracked_files_globs=[
            "dev-requirements-new.txt",
        ],
        base=install_build_environment_step,
        dependency_steps={
            "BUILD_PYTHON_DEPENDENCIES": build_python_dependencies_step,
            "BUILD_OPENSSL": build_openssl_step,
            "BUILD_PYTHON": build_python_step,
        },
        environment_variables={
            "RUST_VERSION": rust_version,
            "RUST_PLATFORM": rust_target_platform,
            "PYTHON_INSTALL_PREFIX": python_install_prefix,
        },
        run_in_remote_docker_if_available=run_in_remote_docker,
    )