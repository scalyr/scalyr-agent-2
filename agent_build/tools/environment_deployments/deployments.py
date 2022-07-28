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


import abc
import argparse
import dataclasses
import hashlib
import json
import os
import pathlib as pl
import re
import shutil
import subprocess
import logging
import inspect
import sys
from functools import wraps
from typing import Union, Optional, List, Dict, Type, Any

from agent_build.tools import common
from agent_build.tools import constants
from agent_build.tools import files_checksum_tracker
from agent_build.tools import build_in_docker
from agent_build.tools.constants import Architecture
from agent_build.tools.constants import AGENT_BUILD_OUTPUT, SOURCE_ROOT
from agent_build.tools.common import check_call_with_log


_PARENT_DIR = pl.Path(__file__).parent.parent.absolute()
_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_DEPLOYMENT_STEPS_PATH = (
    _AGENT_BUILD_PATH / "tools" / "environment_deployments" / "steps"
)


_REL_AGENT_BUILD_PATH = pl.Path("agent_build")
_REL_AGENT_REQUIREMENT_FILES_PATH = _REL_AGENT_BUILD_PATH / "requirement-files"
_REL_DEPLOYMENT_STEPS_PATH = pl.Path("agent_build/tools/environment_deployments/steps")


def save_docker_image(image_name: str, output_path: pl.Path):
    """
    Serialize docker image into file by using 'docker save' command.
    This is made as a separate function only for testing purposes.
    :param image_name: Name of the image to save.
    :param output_path: Result output file.
    """
    with output_path.open("wb") as f:
        common.check_call_with_log(["docker", "save", image_name], stdout=f)


class DeploymentStepError(Exception):
    """
    Special exception class for the deployment step error.
    """

    DEFAULT_LAST_ERROR_LINES_NUMBER = 30

    def __init__(self, stdout, stderr, add_list_lines=DEFAULT_LAST_ERROR_LINES_NUMBER):
        stdout = stdout or ""
        stderr = stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8")

        self.stdout = stdout
        self.stderr = stderr

        stdout = "\n".join(self.stdout.splitlines()[-add_list_lines:])
        stderr = "\n".join(self.stderr.splitlines()[-add_list_lines:])
        message = f"Stdout: {stdout}\n\nStderr:{stderr}"

        super(DeploymentStepError, self).__init__(message)


class DeploymentStep(files_checksum_tracker.FilesChecksumTracker):
    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.
    """

    def __init__(
        self,
        name: str,
        architecture: constants.Architecture,
        tracked_file_globs: List[Union[str,pl.Path]] = None,
        previous_step: Union[str, "DeploymentStep"] = None,
        required_steps: Dict[str, 'DeploymentStep'] = None,
        environment_variables: Dict[str, str] = None,
        cacheable: bool = False,
        cache_as_image: bool = False
    ):
        """
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        super(DeploymentStep, self).__init__(
            tracked_file_globs=tracked_file_globs
        )

        self.name = name
        self.architecture = architecture

        if isinstance(previous_step, DeploymentStep):
            # The previous step is specified.
            # The base docker image is a result image of the previous step.
            self.base_docker_image = previous_step.result_image_name
            self.previous_step = previous_step
        elif isinstance(previous_step, str):
            # The previous step isn't specified, but it is just a base docker image.
            self.base_docker_image = previous_step
            self.previous_step = None
        else:
            # the previous step is not specified.
            self.base_docker_image = None
            self.previous_step = None

        self.environment_variables = environment_variables or {}

        self.required_steps = required_steps or {}

        # personal cache directory of the step.
        self.cache_directory = constants.DEPLOYMENT_CACHE_DIR / self.id
        self.output_directory = constants.DEPLOYMENT_OUTPUT / self.id

        self.cacheable = cacheable
        self.cache_as_image = cache_as_image

    def get_all_cacheable_steps(self):
        result = []
        if self.cacheable:
            result.append(self)

        for step in self.required_steps.values():
            result.extend(step.get_all_cacheable_steps())

        if self.previous_step:
            result.extend(self.previous_step.get_all_cacheable_steps())

        return result

    @property
    def initial_docker_image(self) -> str:
        """
        Name of the docker image of the most parent step. If step is not performed in the docker, returns None,
            otherwise it has to be the name of some public image.
        This is needed for the step's unique name to be distinguishable from other instances of the same step but with
            different base images, for example centos:6 and centos:7
        """
        if not self.previous_step:
            return self.base_docker_image

        return self.previous_step.initial_docker_image

    @property
    def id(self):
        return f"{self.name}_{self.checksum}"

    @property
    def result_image_name(self) -> str:
        """
        The name of the result docker image, just the same as cache key.
        """
        return self.id

    @property
    def runs_in_docker(self) -> bool:
        """
        Whether this step has to be performed in docker or not.
        """
        return self.initial_docker_image is not None

    @property
    def checksum(self) -> str:
        """
        The checksum of the step. It is based on content of the used files + checksum of the previous step.
        """

        sha256 = hashlib.sha256()

        for step in self.required_steps.values():
            sha256.update(step.checksum.encode())

        if self.previous_step:
            sha256.update(self.previous_step.checksum.encode())

        sorted_env_variables = {
            name: self.environment_variables[name]
            for name in sorted(self.environment_variables.keys())
        }

        for name, value in sorted_env_variables.items():
            sha256.update(name.encode())
            sha256.update(value.encode())

        # Calculate the sha256 for each file's content, filename.
        for file_path in self._original_files:
            sha256.update(str(file_path.relative_to(constants.SOURCE_ROOT)).encode())
            sha256.update(file_path.read_bytes())

        return sha256.hexdigest()

    def run(self):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.
        """

        save_to_cache = False

        if self.runs_in_docker and self.cache_as_image:
            # Before the build, check if there is already an image with the same name. The name contains the checksum
            # of all files which are used in it, so the name identity also guarantees the content identity.
            output = (
                common.check_output_with_log(
                    ["docker", "images", "-q", self.result_image_name]
                )
                    .decode()
                    .strip()
            )

            if output:
                # The image already exists, skip the build.
                logging.info(
                    f"Image '{self.result_image_name}' already exists, skip the build and reuse it."
                )
                return

            # If code runs in CI/CD, then check if the image file is already in cache and we can reuse it.
            if common.IN_CICD:
                cached_image_path = self.cache_directory / self.result_image_name
                if cached_image_path.is_file():
                    logging.info(
                        f"Cached image {self.result_image_name} file for the deployment step '{self.name}' has been found, "
                        f"loading and reusing it instead of building."
                    )
                    check_call_with_log(["docker", "load", "-i", str(cached_image_path)])
                    return
                else:
                    # Cache is used but there is no suitable image file. Set the flag to signal that the built
                    # image has to be saved to the cache.
                    save_to_cache = True

        logging.info(f"Run step {self.name}.")
        for step in self.required_steps.values():
            step.run()

        if self.previous_step:
            self.previous_step.run()

        if self.runs_in_docker:
            logging.info(
                f"Build image '{self.result_image_name}' from base image '{self.base_docker_image}' "
                f"for the deployment step '{self.name}'."
            )
            run_func = self._run_in_docker
        else:
            run_func = self._run_locally

        if self.output_directory.exists():
            shutil.rmtree(self.output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)

        try:
            logging.info(f"Start step: {self.id}")
            self._run_function_in_isolated_source_directory(function=run_func)
        except Exception:
            globs = [str(g) for g in self.tracked_file_globs]
            logging.exception(
                f"'{type(self).__name__}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {globs}."
            )
            raise

        if self.runs_in_docker and self.cache_as_image and common.IN_CICD:
            self.cache_directory.mkdir(parents=True, exist_ok=True)
            cached_image_path = self.cache_directory / self.result_image_name
            logging.info(
                f"Saving image '{self.result_image_name}' file for the deployment step {self.name} into cache."
            )
            save_docker_image(
                image_name=self.result_image_name, output_path=cached_image_path
            )



    def _run_in_docker(self):
        """
        This function does the same deployment but inside the docker.
        """
        pass

    @abc.abstractmethod
    def _run_locally(self):
        """
        Run step locally. This has to be implemented in children classes.
        """
        pass

    @abc.abstractmethod
    def _run_in_docker_impl(self, locally: bool = False):
        """
        Run step in docker. This has to be implemented in children classes.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """
        pass

    def _restore_from_cache(self, key: str, path: pl.Path) -> bool:
        """
        Restore file or directory by given key from the step's cache.
        :param key: Name of the file or directory to search in cache.
        :param path: Path where to copy the cached object if it's found.
        :return: True if cached object is found.
        """
        full_path = self.cache_directory / key
        if full_path.exists():
            if full_path.is_dir():
                shutil.copytree(full_path, path)
            else:
                shutil.copy2(full_path, path)
            return True

        return False

    def _save_to_cache(self, key: str, path: pl.Path):
        """

        :param key: Name of the file or directory in cache.
        :param path: Path from where to copy the object to the cache.
        """
        full_path = self.cache_directory / key
        if path.is_dir():
            shutil.copytree(path, full_path)
        else:
            shutil.copy2(path, key)


class DockerFileDeploymentStep(DeploymentStep):
    """
    The deployment step which actions are defined in the Dockerfile. As implies, can be performed only in docker.
    """

    # Path the dockerfile.
    DOCKERFILE_PATH: pl.Path

    def __init__(
        self,
        architecture: constants.Architecture,
        previous_step: Union[str, "DeploymentStep"] = None,
    ):
        super(DockerFileDeploymentStep, self).__init__(
            architecture=architecture, previous_step=previous_step
        )

        # Also add dockerfile to the used file collection, so it is included to the checksum calculation.
        self.used_files = self._init_used_files(
            self.used_files + [type(self).DOCKERFILE_PATH]
        )

    @property
    def runs_in_docker(self) -> bool:
        # This step is in docker by definition.
        return True

    def _run_locally(self):
        # This step is in docker by definition.
        raise RuntimeError("The docker based step can not be performed locally.")

    def _run_in_docker_impl(self, locally: bool = False):
        """
        Perform the actual build by calling docker build with specified dockerfile and other options.
        :param locally: This is ignored, the dockerfile based step can not be performed locally.
        """
        build_in_docker.run_docker_build(
            architecture=self.architecture,
            image_name=self.result_image_name,
            dockerfile_path=type(self).DOCKERFILE_PATH,
            build_context_path=type(self).DOCKERFILE_PATH.parent,
        )


class ShellScriptDeploymentStep(DeploymentStep):
    """
    The deployment step class which is a wrapper around some shell script.
    """

    def __init__(
        self,
        name: str,
        architecture: constants.Architecture,
        script_path: Union[str, pl.Path],
        tracked_file_globs: List[Union[str, pl.Path]] = None,
        previous_step: Union[str, "DeploymentStep"] = None,
        required_steps: Dict[str, 'DeploymentStep'] = None,
        environment_variables: Dict[str, str] = None,
        cacheable: bool = False,
        cache_as_image: bool = False
    ):

        self.script_path = pl.Path(script_path)

        # also add some required files, which are required by this step to the tracked globs list
        tracked_file_globs = tracked_file_globs or []
        tracked_file_globs.extend([
            self.script_path,
            _REL_DEPLOYMENT_STEPS_PATH / "step_runner.sh",
        ])

        super(ShellScriptDeploymentStep, self).__init__(
            name=name,
            architecture=architecture,
            tracked_file_globs=tracked_file_globs,
            previous_step=previous_step,
            required_steps=required_steps,
            environment_variables=environment_variables,
            cacheable=cacheable,
            cache_as_image=cache_as_image
        )

    def _get_command_line_args(self) -> List[str]:
        """
        Create list with the shell command line arguments that has to execute the shell script.
            Optionally also adds cache path to the shell script as additional argument.
        :return: String with shell command that can be executed to needed shell.
        """

        # Determine needed shell interpreter.
        if self.script_path.suffix == ".ps1":
            command_args = ["powershell", self.script_path]
        else:
            shell = "/bin/bash"

            # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
            # and also provides some helper functions such as caching.
            step_runner_script_path = _REL_DEPLOYMENT_STEPS_PATH / "step_runner.sh"

            # To run the shell script of the step we run the 'step_runner' and pass the target script as its argument.
            command_args = [
                shell,
                str(step_runner_script_path),
                str(self.script_path),
            ]

        # Pass cache directory as an additional argument to the
        # script, so it can use the cache too.
        if self.runs_in_docker:
            output_directory = self.docker_output_directory
            cache_directory = self.docker_cache_directory
        else:
            output_directory = self.output_directory
            cache_directory = self.cache_directory

        command_args.append(str(cache_directory))

        command_args.append(str(output_directory))

        return command_args

    def _run_locally(self):
        """
        Run step locally by running the script on current system.
        """
        command_args = self._get_command_line_args()

        # Copy current environment.
        env = os.environ.copy()

        if common.IN_CICD:
            env["IN_CICD"] = "1"

        for step_env_var_name, step in self.required_steps.items():
            env[step_env_var_name] = str(self.output_directory)

        for name, value in self.environment_variables.items():
            env[name] = value

        output = common.run_command(
            command_args,
            env=env,
            debug=True,
        ).decode()

        return output

    @property
    def docker_container_source_root(self):
        return pl.Path("/tmp/agent_source")

    @property
    def docker_output_directory(self):
        return self.docker_container_source_root / f"/tmp/{self.id}"

    @property
    def docker_cache_directory(self):
        return self.docker_container_source_root / f"/tmp/{self.id}_cache"

    def _run_in_docker(self):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_build/tools/tools.build_in_docker'
        module,that allows to execute custom command inside docker by using 'docker build' command. It differs from
        running just in the container because we can benefit from the docker caching mechanism.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """

        # Since we used 'docker build' instead of 'docker run', we can not just mount files, that are used in this step.
        # Instead of that, we'll create intermediate image with all files and use it as base image.

        # To create an intermediate image, first we create container, put all needed files and commit it.
        intermediate_image_name = "agent-build-deployment-step-intermediate"

        # Remove if such intermediate container exists.
        common.check_call_with_log(["docker", "rm", "-f", intermediate_image_name])

        container_name = f"{self.result_image_name}-container".replace(":", "-")

        common.check_call_with_log(["docker", "rm", "-f", container_name])

        try:

            # Get command that has to run shell script.
            command_args = self._get_command_line_args()

            env_options = []
            mount_options = []

            for step_env_var_name, step in self.required_steps.items():
                docker_step_dir = pl.Path("/tmp/required_steps") / step.output_directory.name
                mount_options.extend([
                    "-v",
                    f"{step.output_directory}:{docker_step_dir}"
                ])
                env_options.extend([
                    "-e",
                    f"{step_env_var_name}={docker_step_dir}"
                ])

            for name, value in self.environment_variables.items():
                env_options.extend([
                    "-e",
                    f"{name}={value}"
                ])

            if common.IN_CICD:
                env_options.extend([
                    "-e",
                    "IN_CICD=1"
                ])

            common.check_call_with_log([
                    "docker",
                    "create",
                    "-t",
                    "--name",
                    container_name,
                    "--workdir",
                    str(self.docker_container_source_root),
                    # "-v",
                    # f"{self._isolated_source_root_path}:{self.docker_container_source_root}",
                    # "-v",
                    # f"{self.cache_directory}:{self.docker_cache_directory}",
                    *mount_options,
                    *env_options,
                    self.base_docker_image,
                    *command_args
            ])

            common.run_command([
                "docker",
                "cp",
                "-a",
                f"{self._isolated_source_root_path}/.",
                f"{container_name}:{self.docker_container_source_root}",
            ])

            self.cache_directory.mkdir(parents=True, exist_ok=True)
            common.run_command([
                "docker",
                "cp",
                "-a",
                f"{self.cache_directory}",
                f"{container_name}:{self.docker_cache_directory}",
            ])

            common.run_command([
                "docker",
                "cp",
                "-a",
                f"{self.output_directory}",
                f"{container_name}:{self.docker_output_directory}",
            ])

            common.check_call_with_log([
                "docker",
                "start",
                "--attach",
                container_name
            ])

            if self.cache_as_image:
                check_call_with_log([
                    "docker", "commit", container_name, self.result_image_name
                ])
                return

            common.run_command(
                [
                    "docker",
                    "cp",
                    "-a",
                    f"{container_name}:{self.docker_output_directory}/.",
                    str(self.output_directory)
                ]
            )
            old_cache_directory = self.cache_directory.parent / f"~{self.cache_directory.name}"
            if old_cache_directory.exists():
                shutil.rmtree(old_cache_directory)
            self.cache_directory.rename(old_cache_directory)
            try:
                common.run_command(
                    [
                        "docker",
                        "cp",
                        "-a",
                        f"{container_name}:{self.docker_cache_directory}/.",
                        str(self.cache_directory)
                    ]
                )
            except Exception:
                old_cache_directory.rename(self.cache_directory)
                raise
            else:
                shutil.rmtree(old_cache_directory)

        finally:
            # Remove intermediate container and image.
            common.run_command(["docker", "rm", "-f", intermediate_image_name])
            common.run_command(["docker", "image", "rm", "-f", intermediate_image_name])


class Deployment:
    """
    Abstraction which represents some final desired state of the environment which is defined by set of steps, which are
    instances of the :py:class:`DeploymentStep`
    """

    def __init__(
        self,
        name: str,
        step_classes: List[Type[DeploymentStep]],
        architecture: constants.Architecture = constants.Architecture.UNKNOWN,
        base_docker_image: str = None,
    ):
        """
        :param name: Name of the deployment. Must be unique for the whole project.
        :param step_classes: List of step classes. All those steps classes will be instantiated
            by using current specifics.
        :param architecture: Architecture of the machine where deployment and its steps has to be performed.
        :param base_docker_image: Name of the docker image, if the deployment and all its steps has to be performed
            inside that docker image.
        """
        self.name = name
        self.architecture = architecture
        self.base_docker_image = base_docker_image
        self.cache_directory = constants.DEPLOYMENT_CACHE_DIR / self.name
        self.output_directory = constants.DEPLOYMENT_OUTPUT / self.name

        # List with instantiated steps.
        self.steps = []

        # If docker image is used that is has to be passed as previous step for the first step.
        previous_step = base_docker_image

        for step_cls in step_classes:
            step = step_cls(
                architecture=architecture,
                # specify previous step for the current step.
                previous_step=previous_step,
            )
            previous_step = step
            self.steps.append(step)

        # Add this instance to the global collection of all deployments.
        if self.name in ALL_DEPLOYMENTS:
            raise ValueError(f"The deployment with name: {self.name} already exists.")

        ALL_DEPLOYMENTS[self.name] = self

    @property
    def output_path(self) -> pl.Path:
        """
        Path to the directory where the deployment's steps can put their results.
        """
        return constants.DEPLOYMENT_OUTPUT / self.name

    @property
    def in_docker(self) -> bool:
        """
        Flag that shows whether this deployment has to be performed in docker or not.
        """
        # If the base image is defined, then this deployment is meant to be
        # performed in docker.

        return self.base_docker_image is not None

    @property
    def result_image_name(self) -> Optional[str]:
        """
        The name of the result image of the whole deployment if it has to be performed in docker. It's, logically,
        just a result image name of the last step.
        """
        return self.steps[-1].result_image_name.lower()

    def deploy(self):
        """
        Perform the deployment by running all deployment steps.
        """

        for step in self.steps:
            step.run()


# Special collection where all created deployments are stored. All of the  deployments are saved with unique name as
# key, so it is possible to find any deployment by its name. The ability to find needed deployment step by its name is
# crucial if we want to run it on the CI/CD.
ALL_DEPLOYMENTS: Dict[str, "Deployment"] = {}


def get_deployment_by_name(name: str) -> Deployment:
    return ALL_DEPLOYMENTS[name]


class CacheableBuilder:
    NAME: str
    REQUIRED_BUILDER_CLASSES: List[Type['CacheableBuilder']] = []
    DEPLOYMENT_STEP: DeploymentStep = None

    FQDN: str = None

    def __new__(cls, *args, **kwargs):
        obj = super(CacheableBuilder, cls).__new__(cls)

        init_signature = inspect.signature(obj.__init__)

        input_values = {}
        pos_arg_count = 0
        for name , param in init_signature.parameters.items():
            if param.kind.POSITIONAL_ONLY:
                value = args[pos_arg_count]
                pos_arg_count += 1
            else:
                value = kwargs.get(name, param.default)

            input_values[name] = value

        obj.input_values = input_values
        return obj

    def __init__(
            self,
            required_builders: List['CacheableBuilder'] = None,
            deployment_step: DeploymentStep = None
    ):

        self.output_path = AGENT_BUILD_OUTPUT / "builder_outputs" / type(self).NAME
        self.deployment_step = deployment_step or type(self).DEPLOYMENT_STEP
        self.required_builders = required_builders

    @classmethod
    def get_all_cacheable_deployment_steps(cls) -> List[DeploymentStep]:
        result = []

        result.extend(cls.DEPLOYMENT_STEP.get_all_cacheable_steps())

        for builder_cls in cls.REQUIRED_BUILDER_CLASSES:
            result.extend(builder_cls.get_all_cacheable_deployment_steps())

        return result

    @classmethod
    def get_fully_qualified_name(cls):
        """
        Return fully qualified name of the class.
        :return:
        """
        if cls.FQDN:
            return cls.FQDN

        cls_module = sys.modules[cls.__module__]
        module_path = pl.Path(cls_module.__file__)
        module_parent_rel_dir = module_path.parent.relative_to(SOURCE_ROOT)
        module_full_name = ".".join(str(module_parent_rel_dir).split(os.sep)) + "." + module_path.stem
        return f"{module_full_name}.{cls.__qualname__}"


    def build(self, locally: bool = False):
        """
        The function where the actual build of the package happens.
        :param locally: Force builder to build the package on the current system, even if meant to be done inside
            docker. This is needed to avoid loop when it is already inside the docker.
        """

        if self.output_path.is_dir():
            shutil.rmtree(self.output_path)

        self.output_path.mkdir(parents=True)

        if self.deployment_step:
            runs_in_docker = self.deployment_step.runs_in_docker
        else:
            runs_in_docker = False

        if not common.IN_DOCKER:
            if self.deployment_step:
                self.deployment_step.run()

            if self.required_builders:
                for builder in self.required_builders:
                    builder.build()

            if not runs_in_docker:
                self._build()
                return
        else:
            self._build()
            return

        build_package_script_path = pl.Path("/scalyr-agent-2/agent_build/scripts/builder_helper.py")


        command_args = [
            "python3",
            str(build_package_script_path),
            self.get_fully_qualified_name(),
        ]

        signature = inspect.signature(self.__init__)

        additional_mounts = []
        for name, param in signature.parameters.items():
            value = self.input_values[name]

            if value is None:
                continue

            if isinstance(value, (str, pl.Path)):
                path = pl.Path(value)
                if path.exists() and not str(path).startswith(str(SOURCE_ROOT)):
                    docker_path = pl.Path("/tmp/other_mounts/") / path.relative_to("/")
                    additional_mounts.extend([
                        "-v",
                        f"{path}:{docker_path}"

                    ])

                    value = docker_path

            command_args.extend([
                f"--{name}".replace("_", "-"),
                str(value)
            ])

        base_image_name = self.deployment_step.result_image_name.lower()

        env_options = [
            "-e",
            "AGENT_BUILD_IN_DOCKER=1",
        ]

        if common.IN_CICD:
            env_options.extend([
                "-e",
                "IN_CICD=1"
            ])

        common.check_call_with_log([
            "docker",
            "run",
            "-i",
            "--rm",
            "-v",
            f"{constants.SOURCE_ROOT}:/scalyr-agent-2",
            *additional_mounts,
            *env_options,
            base_image_name,
            *command_args
        ])

        a=10

    def _build(self):
        pass

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):

        parser.add_argument(
            "--locally",
            action="store_true"
        )

        parser.add_argument(
            "--get-all-cacheable-steps",
            dest="get_all_cacheable_steps",
            action="store_true",
        )

        parser.add_argument(
            "--run-all-cacheable-steps",
            dest="run_all_cacheable_steps",
            action="store_true"
        )

        if cls.__init__ is CacheableBuilder.__init__:
            return



        builder_signature = inspect.signature(cls.__init__)
        argument_docs = {}
        arg_name = None
        # Parse argument docstring to put them as 'help' for parser arguments.
        for line in cls.__init__.__doc__.splitlines():
            m = re.match(r"\s*:param ([a-zA-Z_]+):\s*(.*)", line.strip())
            if m:
                arg_name = m.group(1)
                text = m.group(2)
                argument_docs[arg_name] = text.strip()
            elif arg_name:
                argument_docs[arg_name] += line.strip()

        for name, param in builder_signature.parameters.items():
            arg_name = name.replace("_", "-")

            if name == "self":
                continue

            additional_args = {}
            if param.annotation is bool:
                additional_args["action"] = "store_true"

            if "action" not in additional_args:
                if param.annotation in [List, list]:
                    arg_type = str
                else:
                    arg_type = param.annotation
                additional_args["type"] = arg_type

            parser.add_argument(
                f"--{arg_name}",
                dest=name,
                default=param.default,
                required=param.kind == inspect.Parameter.POSITIONAL_ONLY,
                help=argument_docs[name],
                **additional_args
            )

    @classmethod
    def handle_command_line_arguments(
            cls,
            args,
    ):

        if args.get_all_cacheable_steps:
            steps = cls.get_all_cacheable_deployment_steps()
            steps_ids = [step.id for step in steps]
            print(json.dumps(steps_ids))
            exit(0)

        if args.run_all_cacheable_steps:
            steps = cls.get_all_cacheable_deployment_steps()
            for step in steps:
                step.run()
            exit(0)

        if cls.__init__ is not CacheableBuilder.__init__:
            cls_signature = inspect.signature(cls.__init__)
            constructor_args = {}
            for name, param in cls_signature.parameters.items():
                if name == "self":
                    continue

                value = getattr(args, name, None)

                if value:
                    if param.annotation in [List, list]:
                        # this is comma separated string
                        value = value.split(",")

                constructor_args[name] = value
        else:
            constructor_args = {}

        builder = cls(**constructor_args)

        builder.build(locally=args.locally)

