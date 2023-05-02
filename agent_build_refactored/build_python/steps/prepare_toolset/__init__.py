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

from agent_build_refactored.tools.runner import RunnerStep, DockerImageSpec, EnvironmentRunnerStep


def create_step(
    name_suffix: str,
    base_image: DockerImageSpec,
    build_openssl_step: RunnerStep,
    build_python_step: RunnerStep,
    build_dev_requirements_step: RunnerStep,
    python_install_prefix: str,
    run_in_remote_docker: bool = False
):
    """
    :param name_suffix: Suffix for the name of the result step
    :param base_image: Base image for the step
    :param build_openssl_step: Step that builds OpenSSL
    :param build_python_step: Step that build Python
    :param build_dev_requirements_step: Steps that builds agent dev requirements.
    :param python_install_prefix: Install prefix for the Python
    :param run_in_remote_docker: Run in remote docker engine, if possible
    """

    return EnvironmentRunnerStep(
        name=f"prepare_toolset_{name_suffix}",
        script_path=pl.Path(__file__).parent / "prepare_toolset.sh",
        base=base_image,
        dependency_steps={
            "BUILD_OPENSSL": build_openssl_step,
            "BUILD_PYTHON": build_python_step,
            "BUILD_DEV_REQUIREMENTS": build_dev_requirements_step,
        },
        environment_variables={
            "PYTHON_INSTALL_PREFIX": python_install_prefix,
            "FPM_VERSION": "1.14.2",
        },
        run_in_remote_docker_if_available=run_in_remote_docker
    )