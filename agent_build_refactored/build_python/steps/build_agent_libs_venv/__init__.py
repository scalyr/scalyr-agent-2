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
    install_build_environment_step: EnvironmentRunnerStep,
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
    Create step that builds venv with all requirements of the agent project.
    :param name_suffix:
    :param install_build_environment_step:
    :param build_openssl_step:
    :param build_python_step:
    :param build_dev_requirements_step:
    :param python_install_prefix:
    :param agent_subdir_name:
    :param pip_version:
    :param requirements_file_content:
    :param run_in_remote_docker:
    :return:
    """

    return RunnerStep(
        name=f"build_agent_libs_venv_{name_suffix}",
        script_path=pl.Path(__file__).parent / "build_agent_libs_venv.sh",
        tracked_files_globs=[
            "dev-requirements-new.txt",
        ],
        base=install_build_environment_step,
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
