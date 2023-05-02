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

from agent_build_refactored.tools.runner import RunnerStep, EnvironmentRunnerStep


def create_step(
    name_suffix: str,
    prepare_c_runtime_environment_with_python: EnvironmentRunnerStep,
    build_openssl_step: RunnerStep,
    build_python_step: RunnerStep,
    build_dev_requirements_step: RunnerStep,
    python_install_prefix: str,
    agent_subdir_name: str,
    pip_version: str,
    requirements_file_content: str,
    run_in_remote_docker: bool = False
):
    """
    Create step that builds venv with given requirements.
    :param name_suffix: Suffix fot the step name
    :param prepare_c_runtime_environment_with_python: Step that acts like a base for the result step.
        In thi case this is the step that has to have guild tools such as gcc installed.
    :param build_openssl_step: Step that builds openssl
    :param build_python_step: Step that builds python
    :param build_dev_requirements_step: Step that builds all agent project requirements.
        The requirements for the result venv will be reused from those dev requirements.
    :param python_install_prefix: Install prefix for the Python installation
    :param agent_subdir_name: Name of the agent subdirectory
    :param pip_version: Version of pip.
    :param requirements_file_content: Content of the requirements.txt file that has to be installed to a result venv.
    :param run_in_remote_docker: Run in remote docker engine, if needed.
    """

    return RunnerStep(
        name=f"build_agent_libs_venv_{name_suffix}",
        script_path=pl.Path(__file__).parent / "build_agent_libs_venv.sh",
        tracked_files_globs=[
            "dev-requirements-new.txt",
        ],
        base=prepare_c_runtime_environment_with_python,
        dependency_steps={
            "BUILD_OPENSSL": build_openssl_step,
            "BUILD_PYTHON": build_python_step,
            "BUILD_DEV_REQUIREMENTS": build_dev_requirements_step,
        },
        environment_variables={
            "PYTHON_INSTALL_PREFIX": python_install_prefix,
            "SUBDIR_NAME": agent_subdir_name,
            "REQUIREMENTS": requirements_file_content,
            "PIP_VERSION": pip_version,
        },
        run_in_remote_docker_if_available=run_in_remote_docker,
    )
