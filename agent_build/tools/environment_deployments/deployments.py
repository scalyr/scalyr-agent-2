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
import pathlib as pl
import shlex
import re
import subprocess
import logging
from typing import Union, Optional, List, Dict, Type

from agent_build.tools import common
from agent_build.tools import constants
from agent_build.tools import files_checksum_tracker
from agent_build.tools import build_in_docker


_PARENT_DIR = pl.Path(__file__).parent.parent.absolute()
_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_DEPLOYMENT_STEPS_PATH = _AGENT_BUILD_PATH / "tools" / "environment_deployments" / "steps"


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
        common.check_call_with_log(
            ["docker", "save", image_name], stdout=f
        )


class DeploymentStepError(Exception):
    """
    Special exception class for the deployment step error.
    """
    _LAST_ERROR_LINES_NUMBER = 20

    def __init__(self, stdout, add_list_lines=20):
        self.stdout = stdout
        last_lines = self.stdout.splitlines()[-add_list_lines:]
        message = "Output: \n" + "\n".join(last_lines)
        super(DeploymentStepError, self).__init__(message)


class DeploymentStep(files_checksum_tracker.FilesChecksumTracker):
    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.
    """

    # Set of files that are somehow used during the step. Needed to calculate the checksum of the whole step, so it can
    # be used as cache key.
    USED_FILES: List[pl.Path] = []

    def __init__(
        self,
        architecture: constants.Architecture,
        previous_step: Union[str, "DeploymentStep"] = None,
    ):
        """
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        super(DeploymentStep, self).__init__()

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

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        return type(self).USED_FILES

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

        return self._get_files_checksum(
            additional_seed=additional_seed
        )

    def run(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.

        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it.
        :param locally: A special flag that forces a step to be performed locally on the current system, even
            if it meant to be performed inside docker. This is needed to avoid the loop when the step is already in the
            docker.
        """

        def run_step():
            if self.in_docker:
                self._run_in_docker(cache_dir=cache_dir)
            else:
                self._run_locally(cache_dir=cache_dir)

        self._run_function_in_isolated_source_directory(
            function=run_step
        )

    def _run_in_docker(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        This function does the same deployment but inside the docker.
        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it. In case of docker, the whole result image of the step will be cached.
        """

        # Before the build, check if there is already an image with the same name. The name contains the checksum
        # of all files which are used in it, so the name identity also guarantees the content identity.
        output = (
            common.check_output_with_log(["docker", "images", "-q", self.result_image_name])
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

        # If cache directory is specified, then check if the image file is already there and we can reuse it.
        if cache_dir:
            cache_dir = pl.Path(cache_dir)
            cached_image_path = cache_dir / self.result_image_name
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

        if cache_dir and save_to_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_image_path = cache_dir / self.result_image_name
            logging.info(
                f"Saving image '{self.result_image_name}' file for the deployment step {self.name} into cache."
            )
            save_docker_image(
                image_name=self.result_image_name,
                output_path=cached_image_path
            )


    @abc.abstractmethod
    def _run_locally(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run step locally. This has to be implemented in children classes.
        :param cache_dir: Path of the cache directory. If specified, then the step may save or reuse some intermediate
            result using it.
        """
        pass

    @abc.abstractmethod
    def _run_in_docker_impl(
        self, cache_dir: Union[str, pl.Path] = None, locally: bool = False
    ):
        """
        Run step in docker. This has to be implemented in children classes.
        :param cache_dir: Path of the cache directory.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """
        pass


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

    def _run_locally(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        # This step is in docker by definition.
        raise RuntimeError("The docker based step can not be performed locally.")

    def _run_in_docker_impl(
        self, cache_dir: Union[str, pl.Path] = None, locally: bool = False
    ):
        """
        Perform the actual build by calling docker build with specified dockerfile and other options.
        :param cache_dir: Path of the cache directory.
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

    # Path to  the script file that has to be executed during the step.
    SCRIPT_PATH: pl.Path

    def __init__(
        self,
        architecture: constants.Architecture,
        previous_step: Union[str, "DeploymentStep"] = None,
    ):
        super(ShellScriptDeploymentStep, self).__init__(
            architecture=architecture, previous_step=previous_step
        )

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        # Also add script to the used file collection, so it is included to the checksum calculation.
        script_files = [
            type(self).SCRIPT_PATH,
            _REL_DEPLOYMENT_STEPS_PATH / "step_runner.sh",
        ]
        return super(ShellScriptDeploymentStep, self)._tracked_file_globs + script_files

    def _get_command_line_args(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ) -> List[str]:
        """
        Create list with the shell command line arguments that has to execute the shell script.
            Optionally also adds cache path to the shell script as additional argument.
        :param cache_dir: Path to the cache dir.
        :return: String with shell command that can be executed to needed shell.
        """

        # Determine needed shell interpreter.
        if type(self).SCRIPT_PATH.suffix == ".ps1":
            command_args = ["powershell", str(type(self).SCRIPT_PATH)]
        else:
            shell = "/bin/sh"

            # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
            # and also provides some helper functions such as caching.
            step_runner_script_path = _REL_DEPLOYMENT_STEPS_PATH / "step_runner.sh"

            # To run the shell script of the step we run the 'step_runner' and pass the target script as its argument.
            command_args = [shell, str(step_runner_script_path), str(type(self).SCRIPT_PATH)]

        # If cache directory is presented, then we pass it as an additional argument to the
        # script, so it can use the cache too.
        if cache_dir:
            command_args.append(str(pl.Path(cache_dir)))

        return command_args

    def _run_locally(
        self,
        cache_dir: Union[str, pl.Path] = None,
    ):
        """
        Run step locally by running the script on current system.
        :param cache_dir: Path of the cache directory. If specified, then the script may save or reuse some intermediate
            results in it.
        """
        command_args = self._get_command_line_args(
            cache_dir=cache_dir
        )

        try:
            output = common.run_command(
                command_args,
                debug=True,
            ).decode()
        except subprocess.CalledProcessError as e:
            raise DeploymentStepError(
                stdout=e.stdout.decode()
            ) from None

        return output

    def _run_in_docker_impl(
        self, cache_dir: Union[str, pl.Path] = None, locally: bool = False
    ):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_build/tools/tools.build_in_docker'
        module,that allows to execute custom command inside docker by using 'docker build' command. It differs from
        running just in the container because we can benefit from the docker caching mechanism.
        :param cache_dir: Path of the cache directory.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """

        # Since we used 'docker build' instead of 'docker run', we can not just mount files, that are used in this step.
        # Instead of that, we'll create intermediate image with all files and use it as base image.

        # To create an intermediate image, first we create container, put all needed files and commit it.
        intermediate_image_name = f"agent-build-deployment-step-intermediate"

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
                    self.base_docker_image
                ],
            )

            # Copy used files to the intermediate container.
            container_source_root = pl.Path(f"/tmp/agent_source")
            common.run_command([
                "docker",
                "cp",
                "-a",
                f"{self._isolated_source_root_path}/.",
                f"{intermediate_image_name}:{container_source_root}"
            ])

            # Commit intermediate container as image.
            common.run_command(
                ["docker", "commit", intermediate_image_name, intermediate_image_name]
            )

            # Get command that has to run shell script.
            command_args = self._get_command_line_args(cache_dir=cache_dir)

            # Run command in the previously created intermediate image.
            try:
                build_in_docker.build_stage(
                    command=shlex.join(command_args),
                    stage_name="step-build",
                    architecture=self.architecture,
                    image_name=self.result_image_name,
                    work_dir=container_source_root,
                    base_image_name=intermediate_image_name,
                    debug=True
                )
            except build_in_docker.RunDockerBuildError as e:
                raise DeploymentStepError(stdout=e.stdout)

        finally:
            # Remove intermediate container and image.
            common.run_command(["docker", "rm", "-f", intermediate_image_name])
            common.run_command(
                ["docker", "image", "rm", "-f", intermediate_image_name]
            )


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

    def deploy(
        self,
        cache_dir: pl.Path = None,
    ):
        """
        Perform the deployment by running all deployment steps.

        :param cache_dir: Cache directory. If specified, all steps of the deployment will use it to
            save their results in it.
        :return:
        """

        for step in self.steps:

            # If cache is specified, then create separate sub-folder in it for each step.
            # NOTE: Those sub-folders are used by our special Github-Actions action that caches all such sub-folders to
            # the Github Actions cache. See more in ".github/actions/perform-deployment"
            if cache_dir:
                step_cache_path = cache_dir.absolute() / step.cache_key
                if not step_cache_path.is_dir():
                    step_cache_path.mkdir(parents=True)
            else:
                step_cache_path = None

            step.run(
                cache_dir=step_cache_path,
            )


# Special collection where all created deployments are stored. All of the  deployments are saved with unique name as
# key, so it is possible to find any deployment by its name. The ability to find needed deployment step by its name is
# crucial if we want to run it on the CI/CD.
ALL_DEPLOYMENTS: Dict[str, "Deployment"] = {}


def get_deployment_by_name(name: str) -> Deployment:
    return ALL_DEPLOYMENTS[name]


# Step that runs small script which installs requirements for the test/dev environment.
class InstallTestRequirementsDeploymentStep(ShellScriptDeploymentStep):
    SCRIPT_PATH = _REL_DEPLOYMENT_STEPS_PATH / "deploy-test-environment.sh"
    USED_FILES = [
        _REL_AGENT_REQUIREMENT_FILES_PATH / "testing-requirements.txt",
        _REL_AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt",
    ]


# Create common test environment that will be used by GitHub Actions CI
COMMON_TEST_ENVIRONMENT = Deployment(
    # Name of the deployment.
    # Call the local './.github/actions/perform-deployment' action with this name.
    "test_environment",
    step_classes=[InstallTestRequirementsDeploymentStep],
)