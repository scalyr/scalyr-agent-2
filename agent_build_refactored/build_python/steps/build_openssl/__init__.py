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
    openssl_version: str,
    openssl_major_version: int,
    install_build_environment_step: EnvironmentRunnerStep,
    download_build_dependencies_step: RunnerStep,
    run_in_remote_docker: bool = False
):
    """
    Create step that builds OpenSSL.
    :param name_suffix: Suffix fot the step name
    :param openssl_version: Version of OpenSSL
    :param openssl_major_version: Major version of the OpenSSL version.
    :param install_build_environment_step: Step that acts like a base for the result step.
    :param download_build_dependencies_step: Step that downloads source code for python interpreter and its
        dependencies.
    :param run_in_remote_docker: Run in remote docker engine, if needed.

    :return:
    """
    script_name = f"build_openssl_{openssl_major_version}.sh"

    return RunnerStep(
        name=f"build_openssl_{openssl_major_version}_{name_suffix}",
        script_path=pl.Path(__file__).parent / script_name,
        base=install_build_environment_step,
        dependency_steps={
            "DOWNLOAD_BUILD_DEPENDENCIES": download_build_dependencies_step,
        },
        environment_variables={
            "DISTRO_NAME": install_build_environment_step.initial_docker_image.name,
            "OPENSSL_VERSION": openssl_version
        },
        run_in_remote_docker_if_available=run_in_remote_docker,
    )