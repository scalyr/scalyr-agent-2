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
import enum
import shutil
from typing import List
import pathlib as pl
import subprocess
import shlex
import logging

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()
AGENT_BUILD_OUTPUT = SOURCE_ROOT / "agent_build_output"
PACKAGE_BUILDER_OUTPUT = AGENT_BUILD_OUTPUT / "package"

# A counter for all commands that have been executed since start of the program.
# Just for more informative logging.
_COMMAND_COUNTER = 0


def init_logging():
    """
    Init logging and defined additional logging fields to logger.
    """

    logging.basicConfig(
        level=logging.INFO,
        format=f"[%(levelname)s][%(module)s:%(lineno)s] %(message)s",
    )


def subprocess_command_run_with_log(func):
    """
    Wrapper for 'subprocess.check_call' and 'subprocess.check_output' function that also logs
    additional info when command is executed.
    :param func: Function to wrap.
    """

    def wrapper(*args, **kwargs):

        global _COMMAND_COUNTER

        # Make info message with all command line arguments.
        cmd_args = kwargs.get("args")
        if cmd_args is None:
            cmd_args = args[0]
        if isinstance(cmd_args, list):
            # Create command string.
            cmd_str = shlex.join(cmd_args)
        else:
            cmd_str = cmd_args

        number = _COMMAND_COUNTER
        _COMMAND_COUNTER += 1
        logging.info(f" ### RUN COMMAND #{number}: '{cmd_str}'. ###", stacklevel=3)
        try:
            result = func(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            logging.info(f" ### COMMAND #{number} FAILED. ###\n", stacklevel=3)
            raise e from None
        else:
            logging.info(f" ### COMMAND #{number} ENDED. ###\n", stacklevel=3)
            return result

    return wrapper


check_call_with_log = subprocess_command_run_with_log(subprocess.check_call)
check_output_with_log = subprocess_command_run_with_log(subprocess.check_output)


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

        check_call_with_log(command_args)

    def kill(self):
        check_call_with_log(["docker", "rm", "-f", self.name])

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.kill()


class LocalRegistryContainer(DockerContainer):
    """
    Container start runs local docker registry inside.
    """

    def __init__(
        self, name: str, registry_port: int, registry_data_path: pl.Path = None
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


def clean_agent_build_steps_output(
        build_root: pl.Path
):
    """
    Helper function that helps to clean output directories of the unfinished/failed build steps.
    """
    for child_path in build_root.iterdir():
        # Delete all directories that start with '~' that means that they are not finished.
        if child_path.is_dir() and child_path.name.startswith("~"):
            shutil.rmtree(child_path)


class Architecture(enum.Enum):
    """
    Architecture types.
    """

    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARM = "arm"
    ARMV7 = "armv7"
    ARMV8 = "armv8"
    UNKNOWN = "unknown"

    @property
    def as_docker_platform(self) -> str:
        global _ARCHITECTURE_TO_DOCKER_PLATFORM
        return _ARCHITECTURE_TO_DOCKER_PLATFORM[self]


_ARCHITECTURE_TO_DOCKER_PLATFORM = {
    Architecture.X86_64: "linux/amd64",
    Architecture.ARM64: "linux/arm64",
    # For Raspberry Pi and other lower powered armv7 based ARM platforms
    Architecture.ARM: "linux/arm",
    Architecture.ARMV7: "linux/arm/v7",
    Architecture.ARMV8: "linux/arm/v8",
    # Handle unknown architecture value as x86_64
    Architecture.UNKNOWN: "linux/amd64",
}