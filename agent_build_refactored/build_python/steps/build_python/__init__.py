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
        download_build_dependencies_step: RunnerStep,
        install_build_environment_step: EnvironmentRunnerStep,
        build_python_dependencies_step: RunnerStep,
        build_openssl_step: RunnerStep,
        python_version: str,
        python_short_version: str,
        python_install_prefix: str,
        pip_version: str,
        run_in_remote_docker: bool = False
):
    """
    Create step that build Python interpreter.
    :param name_suffix: Suffix fot the step name
    :param download_build_dependencies_step: Step that downloads source code for python interpreter and its
    dependencies.
    :param install_build_environment_step: Step that acts like a base for the result step.
    :param build_python_dependencies_step: Steps that build all dependencies for the Python interpreter.
    :param build_openssl_step: Step that builds openssl
    :param python_version: Version of Python.
    :param python_short_version: Short version of Python, without last patch part.
    :param python_install_prefix: Install prefix for the Python installation
    :param pip_version: Version of the pip.
    :param run_in_remote_docker:  Run in remote docker engine, if needed.
    """
    additional_options = ""

    # TODO: find out why enabling LTO optimization of ARM ends with error.
    # Disable it for now.
    if install_build_environment_step.architecture == Architecture.X86_64:
        additional_options += "--with-lto"

    return RunnerStep(
        name=f"build_python{name_suffix}",
        script_path=pl.Path(__file__).parent / "build_python.sh",
        base=install_build_environment_step,
        dependency_steps={
            "DOWNLOAD_BUILD_DEPENDENCIES": download_build_dependencies_step,
            "BUILD_PYTHON_DEPENDENCIES": build_python_dependencies_step,
            "BUILD_OPENSSL": build_openssl_step,
        },
        environment_variables={
            "PYTHON_VERSION": python_version,
            "PYTHON_SHORT_VERSION": python_short_version,
            "ADDITIONAL_OPTIONS": additional_options,
            "INSTALL_PREFIX": python_install_prefix,
            "PIP_VERSION": pip_version,
        },
        run_in_remote_docker_if_available=run_in_remote_docker,
    )