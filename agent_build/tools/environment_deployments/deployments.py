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
import os
import pathlib as pl
import shlex
import re
import shutil
import subprocess
import logging
from typing import Union, Optional, List, Dict, Type

from agent_build.tools import common
from agent_build.tools import constants
from agent_build.tools import files_checksum_tracker
from agent_build.tools import build_in_docker


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
        deployment: "Deployment",
        architecture: constants.Architecture,
        previous_step: Union[str, "DeploymentStep"] = None,
    ):
        """
        :param deployment: The deployment instance where this step is added.
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        super(DeploymentStep, self).__init__()

        self.architecture = architecture
        self.deployment = deployment

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

        # personal cache directory of the step.
        self.cache_directory = self.deployment.cache_directory / self.cache_key
        self.output_directory = self.deployment.output_directory / self.unique_name

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        """
        Get filed that has to be tracked by the step in order to calculate checksum, for caching.
        """
        return []

    @property
    def name(self) -> str:
        """
        Name of the deployment step. It is just a name of the class name but in snake case.
        """
        class_name = type(self).__name__
        return re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()

    @property
    def unique_name(self) -> str:
        """
        Create name for the step. It has to contain all specific information about the step,
        so it can be used as unique cache key.
        """

        name = self.name

        if self.previous_step:
            name = f"{name}_{self.previous_step.name}"

        name = f"{name}_{self.architecture.value}"

        # If its a docker deployment, then add the docker image to the name
        if self.in_docker:
            image_suffix = self.initial_docker_image.replace(":", "_")
            name = f"{name}_{image_suffix}"

        return name

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
    def cache_key(self) -> str:
        """
        Unique cache key based on the name of the step and on the content of used files.
        """
        return f"{self.unique_name}_{self.checksum}"

    @property
    def result_image_name(self) -> str:
        """
        The name of the result docker image, just the same as cache key.
        """
        return self.cache_key

    @property
    def in_docker(self) -> bool:
        """
        Whether this step has to be performed in docker or not.
        """
        return self.initial_docker_image is not None

    @property
    def checksum(self) -> str:
        """
        The checksum of the step. It is based on content of the used files + checksum of the previous step.
        """

        if self.previous_step:
            additional_seed = self.previous_step.checksum
        else:
            additional_seed = None

        return self._get_files_checksum(additional_seed=additional_seed)

    def run(self):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.
        """

        if self.in_docker:
            run_func = self._run_in_docker
        else:
            run_func = self._run_locally

        self._run_function_in_isolated_source_directory(function=run_func)

    def _run_in_docker(self):
        """
        This function does the same deployment but inside the docker.
        """

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

        save_to_cache = False

        # If code runs in CI/CD, then check if the image file is already in cache and we can reuse it.
        if common.IN_CICD:
            cached_image_path = self.cache_directory / self.result_image_name
            if cached_image_path.is_file():
                logging.info(
                    f"Cached image {self.result_image_name} file for the deployment step '{self.name}' has been found, "
                    f"loading and reusing it instead of building."
                )
                common.run_command(["docker", "load", "-i", str(cached_image_path)])
                return
            else:
                # Cache is used but there is no suitable image file. Set the flag to signal that the built
                # image has to be saved to the cache.
                save_to_cache = True

        logging.info(
            f"Build image '{self.result_image_name}' from base image '{self.base_docker_image}' "
            f"for the deployment step '{self.name}'."
        )

        self._run_in_docker_impl()

        if common.IN_CICD and save_to_cache:
            self.cache_directory.mkdir(parents=True, exist_ok=True)
            cached_image_path = self.cache_directory / self.result_image_name
            logging.info(
                f"Saving image '{self.result_image_name}' file for the deployment step {self.name} into cache."
            )
            save_docker_image(
                image_name=self.result_image_name, output_path=cached_image_path
            )

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
    def in_docker(self) -> bool:
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
        deployment: "Deployment",
        architecture: constants.Architecture,
        previous_step: Union[str, "DeploymentStep"] = None,
    ):
        super(ShellScriptDeploymentStep, self).__init__(
            deployment=deployment,
            architecture=architecture,
            previous_step=previous_step,
        )

    @property
    @abc.abstractmethod
    def script_path(self) -> pl.Path:
        """
        Path to  the script file that has to be executed during the step.
        """
        pass

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        # Also add script to the used file collection, so it is included to the checksum calculation.
        script_files = [
            self.script_path,
            _REL_DEPLOYMENT_STEPS_PATH / "step_runner.sh",
        ]
        return super(ShellScriptDeploymentStep, self)._tracked_file_globs + script_files

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
        command_args.append(str(pl.Path(self.cache_directory)))

        command_args.append(str(self.deployment.output_directory))

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

        try:
            output = common.run_command(
                command_args,
                env=env,
                debug=True,
            ).decode()
        except subprocess.CalledProcessError as e:
            raise DeploymentStepError(stdout=e.stdout, stderr=e.stderr) from None

        return output

    def _run_in_docker_impl(self, locally: bool = False):
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
        common.run_command(["docker", "rm", "-f", intermediate_image_name])

        try:

            # Create an intermediate container from the base image.
            common.run_command(
                [
                    "docker",
                    "create",
                    "--platform",
                    self.architecture.as_docker_platform.value,
                    "--name",
                    intermediate_image_name,
                    self.base_docker_image,
                ],
            )

            # Copy used files to the intermediate container.
            container_source_root = pl.Path("/tmp/agent_source")
            common.run_command(
                [
                    "docker",
                    "cp",
                    "-a",
                    f"{self._isolated_source_root_path}/.",
                    f"{intermediate_image_name}:{container_source_root}",
                ]
            )

            # Commit intermediate container as image.
            common.run_command(
                ["docker", "commit", intermediate_image_name, intermediate_image_name]
            )

            # Get command that has to run shell script.
            command_args = self._get_command_line_args()

            # Run command in the previously created intermediate image.
            try:
                build_in_docker.build_stage(
                    command=shlex.join(command_args),
                    stage_name="step-build",
                    architecture=self.architecture,
                    image_name=self.result_image_name,
                    work_dir=container_source_root,
                    base_image_name=intermediate_image_name,
                    debug=True,
                )
            except build_in_docker.RunDockerBuildError as e:
                raise DeploymentStepError(stdout=e.stdout, stderr=e.stderr)

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
                deployment=self,
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


# Step that runs small script which installs requirements for the test/dev environment.
class InstallTestRequirementsDeploymentStep(ShellScriptDeploymentStep):
    @property
    def script_path(self) -> pl.Path:
        return _REL_DEPLOYMENT_STEPS_PATH / "deploy-test-environment.sh"

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        globs = super(InstallTestRequirementsDeploymentStep, self)._tracked_file_globs
        globs.append(_REL_AGENT_REQUIREMENT_FILES_PATH / "*.txt")
        return globs


_REL_DOCKER_BASE_IMAGE_STEP_PATH = _REL_DEPLOYMENT_STEPS_PATH / "docker-base-images"
_REL_AGENT_BUILD_DOCKER_PATH = _REL_AGENT_BUILD_PATH / "docker"


_REL_DEPLOYMENT_BUILD_BASE_IMAGE_STEP = (
    _REL_DEPLOYMENT_STEPS_PATH / "build_base_docker_image"
)


class BuildDockerBaseImageStep(ShellScriptDeploymentStep):
    """
    This deployment step is responsible for the building of the base image of the agent docker images.
    It runs shell script that builds that base image and pushes it to the local registry that runs in container.
    After push, registry is shut down, but it's data root is preserved. This step puts this
    registry data root to the output of the deployment, so the builder of the final agent docker image can access this
    output and fetch base images from registry root (it needs to start another registry and mount existing registry
    root).
    """

    # Suffix of that python image, that is used as the base image for our base image.
    # has to match one of the names from the 'agent_build/tools/environment_deployments/steps/build_base_docker_image'
    # directory, except 'build_base_images_common_lib.sh', it is a helper library.
    BASE_DOCKER_IMAGE_TAG_SUFFIX: str

    @property
    def script_path(self) -> pl.Path:
        """
        Resolve path to the base image builder script which depends on suffix on the base image.
        """
        return (
            _REL_DEPLOYMENT_BUILD_BASE_IMAGE_STEP
            / f"{type(self).BASE_DOCKER_IMAGE_TAG_SUFFIX}.sh"
        )

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        globs = super(BuildDockerBaseImageStep, self)._tracked_file_globs
        # Track the dockerfile...
        globs.append(_REL_AGENT_BUILD_DOCKER_PATH / "Dockerfile.base")
        # and helper lib for base image builder.
        globs.append(
            _REL_DEPLOYMENT_BUILD_BASE_IMAGE_STEP / "build_base_images_common_lib.sh"
        )
        # .. and requirement files...
        globs.append(
            _REL_AGENT_REQUIREMENT_FILES_PATH / "docker-image-requirements.txt"
        )
        globs.append(_REL_AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt")
        globs.append(_REL_AGENT_REQUIREMENT_FILES_PATH / "main-requirements.txt")
        return globs


class BuildDebianDockerBaseImageStep(BuildDockerBaseImageStep):
    """
    Subclass that builds agent's base docker image based on debian (slim)
    """

    BASE_DOCKER_IMAGE_TAG_SUFFIX = "slim"


class BuildAlpineDockerBaseImageStep(BuildDockerBaseImageStep):
    """
    Subclass that builds agent's base docker image based on alpine.
    """

    BASE_DOCKER_IMAGE_TAG_SUFFIX = "alpine"


# Create common test environment that will be used by GitHub Actions CI
COMMON_TEST_ENVIRONMENT = Deployment(
    # Name of the deployment.
    # Call the local './.github/actions/perform-deployment' action with this name.
    "test_environment",
    step_classes=[InstallTestRequirementsDeploymentStep],
)
