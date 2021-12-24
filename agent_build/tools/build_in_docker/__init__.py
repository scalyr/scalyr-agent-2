# Copyright 2014-2021 Scalyr Inc.
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

# This is a helper module that helps to run custom command inside the docker build context.
# Since we can deploy some of the deployments (agent_build/tools/environment_deployments/deployments.py) inside docker,
# Using 'docker build' is more beneficial that 'docker run' because of the docker caching.


import pathlib as pl
import os
import subprocess
from typing import Dict, List

from agent_build.tools import constants
from agent_build.tools import common

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent.parent


class RunDockerBuildError(Exception):
    def __init__(self, stdout):
        self.stdout = stdout


def run_docker_build(
    architecture: constants.Architecture,
    image_name: str,
    dockerfile_path: pl.Path,
    build_context_path: pl.Path,
    build_args: Dict[str, str] = None,
    debug: bool = False,
):
    """
    Just a simple wrapper around "docker build" command.
    :param architecture: Architecture of the build. Translated to the docker's --platform option.
    :param image_name: Name of the result image.
    :param dockerfile_path: Path to the Dockerfile.
    :param build_context_path: Build context path.
    :param build_args: Dockerfile build arguments (--build-arg).
    :param debug: Enable output of True.
    """

    # Enable docker Buildkit.
    env = os.environ.copy()
    env["DOCKER_BUILDKIT"] = "1"

    build_args = build_args or {}

    build_arg_options = []

    for name, value in build_args.items():
        build_arg_options.append("--build-arg")
        build_arg_options.append(f"{name}={value}")

    try:
        output = common.run_command(
            [
                "docker",
                "build",
                "--platform",
                architecture.as_docker_platform.value,
                "-t",
                image_name,
                *build_arg_options,
                "--label",
                "scalyr-agent-build",
                "-f",
                str(dockerfile_path),
                str(build_context_path),
            ],
            env=env,
            stderr=subprocess.STDOUT,
            debug=debug,
        ).decode()
    except subprocess.CalledProcessError as e:
        raise RunDockerBuildError(stdout=e.stdout)

    return output


def build_stage(
    command: str,
    stage_name: str,
    architecture: constants.Architecture,
    image_name: str,
    base_image_name: str,
    work_dir: pl.Path = None,
    output_path_mappings: Dict[pl.Path, pl.Path] = None,
    debug: bool = False,
):
    """
    Run a custom command using the 'docker build' by specifying special Dockerfile which is located
        in the same directory with current module.
    :param command: Command to execute.
    :param stage_name: Name of one of the stages in the Dockerfile. Those stages are used in different scenarios, for
        example agent package build or package tests, and include different set of files needed for those scenarios.
    :param architecture: Architecture of the build. Translated to the docker's '--platform' option.
    :param image_name: Name of the result image.
    :param base_image_name: Name of the base image to use.
    :param work_dir: Set working directory.
    :param output_path_mappings: Dict with mapping of the host paths to the paths that are used inside the docker.
        After the build is completed, files or folders that are located inside the docker will be copied to the
        appropriate host paths.
    :param debug: Enable output if True.
    """
    run_docker_build(
        architecture=architecture,
        image_name=image_name,
        dockerfile_path=__PARENT_DIR__ / "Dockerfile",
        build_context_path=__SOURCE_ROOT__,
        build_args={
            "BASE_IMAGE_NAME": base_image_name,
            "COMMAND": command,
            "BUILD_STAGE": stage_name,
            "WORK_DIR": str(work_dir),
        },
        debug=debug,
    )

    # If there are output mapping specified, than we has to copy result files from the result build.
    # To do that we have to create a container and copy files from it.
    if output_path_mappings:
        container_name = image_name
        # Remove the container with the same name if exists.
        common.run_command(["docker", "rm", "-f", container_name])
        try:

            output_path_mappings = output_path_mappings or {}

            # Create the container.
            common.run_command(
                ["docker", "create", "--name", container_name, image_name]
            )

            for host_path, docker_path in output_path_mappings.items():
                common.run_command(
                    [
                        "docker",
                        "cp",
                        "-a",
                        # f"{container_name}:/tmp/build/.",
                        # str(output_path),
                        f"{container_name}:{docker_path}/.",
                        str(host_path),
                    ],
                )

        finally:
            # Remove container.
            common.run_command(["docker", "rm", "-f", container_name])


class DockerContainer:
    """
    Simple wrapper around docker container that allows to use context manager to clean up when container is not
    needed anymore.
    NOTE: The 'docker' library is not used on purpose, since there's only one abstraction that is needed. Using
    docker through the docker CLI is much easier and does not require the "docker" lib as dependency.
    """
    def __init__(
            self,
            name: str,
            image_name: str,
            ports: List[str] = None,
            mounts: List[str] = None,
    ):
        self.name = name
        self.image_name = image_name
        self.mounts = mounts or []
        self.ports = ports or []

    def start(self):

        # Kill the previously run container, if exists.
        self.kill()

        command_args = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.name,
        ]

        for port in self.ports:
            command_args.append("-p")
            command_args.append(port)

        for mount in self.mounts:
            command_args.append("-v")
            command_args.append(mount)

        command_args.append(self.image_name)

        common.check_call_with_log(
            command_args
        )

    def kill(self):
        common.run_command(["docker", "rm", "-f", self.name])

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.kill()


class LocalRegistryContainer(DockerContainer):
    """
    Container start runs local docker registry inside.
    """
    def __init__(
            self,
            name: str,
            registry_port: int,
            registry_data_path: pl.Path = None
    ):
        """
        :param name: Name of the container.
        :param registry_port: Host port that will be mapped to the registry's port.
        :param registry_data_path: Host directory that will be mapped to the registry's data root.
        """
        super(LocalRegistryContainer, self).__init__(
            name=name,
            image_name="registry:2",
            ports=[f"{registry_port}:5000"],
            mounts=[f"{registry_data_path}:/var/lib/registry"],
        )
