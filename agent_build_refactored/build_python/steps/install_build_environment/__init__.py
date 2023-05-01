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

from agent_build_refactored.tools.runner import DockerImageSpec, EnvironmentRunnerStep


def create_step(
    name_suffix: str,
    base_image: DockerImageSpec,
    run_in_remote_docker: bool = False
) -> EnvironmentRunnerStep:
    """
    Create step that prepares its result environment by installing gcc and other build tools that bay be needed
        in order to compile Python interpreter and other.
    :param name_suffix: Suffix for the step name.
    :param base_image: Spec if the docker image that is used as the base for this step.
    :param run_in_remote_docker: Run in remote docker engine, if needed.
    :return:
    """
    if base_image.name == "centos:6":
        script_name = "install_gcc_centos_6.sh"
    else:
        script_name = "install_gcc_centos_7.sh"

    return EnvironmentRunnerStep(
        name=f"install_build_environment_{name_suffix}",
        script_path=pl.Path(__file__).parent / script_name,
        base=base_image,
        run_in_remote_docker_if_available=run_in_remote_docker,
    )