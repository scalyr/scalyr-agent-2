# Copyright 2014-2022 Scalyr Inc.
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


import argparse
import dataclasses
import functools
import hashlib
import json
import os
import pathlib as pl
import shutil
import logging
import inspect
import sys
from typing import Union, Optional, List, Dict, Type


from agent_build_refactored.tools.constants import SOURCE_ROOT, DockerPlatformInfo
from agent_build_refactored.tools import (
    check_call_with_log,
    DockerContainer,
    UniqueDict,
    check_output_with_log,
    IN_DOCKER,
    IN_CICD,
)

log = logging.getLogger(__name__)


def remove_directory_in_docker(path: pl.Path):
    """
    Since we produce some artifacts inside docker containers, we may face difficulties with
    deleting the old ones because they may be created inside the container with the root user.
    The workaround for that to delegate that deletion to a docker container as well.
    """

    # In order to be able to remove the whole directory, we mount parent directory.
    with DockerContainer(
        name="agent_build_step_trash_remover",
        image_name="ubuntu:22.04",
        mounts=[f"{path.parent}:/parent"],
        command=["rm", "-r", f"/parent/{path.name}"],
        detached=False,
    ):
        pass


@dataclasses.dataclass
class DockerImageSpec:
    """Simple data class which represents combination of the image name and docker platform."""

    name: str
    platform: DockerPlatformInfo

    def save_docker_image(self, output_path: pl.Path):
        """
        Serialize docker image into file by using 'docker save' command.
        :param output_path: Result output file.
        """

        check_call_with_log(["docker", "save", self.name, "--output", str(output_path)])


@dataclasses.dataclass
class GitHubActionsSettings:
    """Dataclass that stores settings for how step has to be executed on GitHub Actions CI/CD"""

    # Flag that indicates that step has to be cached by GHA CI/CD
    cacheable: bool = False

    # Flag that indicates that this step has to be executed in a separate job during GHA CI/CD run.
    # In case of multiple, long-running steps, this has to decrease overall build time.
    pre_build_in_separate_job: bool = False


class RunnerStep:
    """
    Base abstraction that represents a shell/python script that has to be executed by the Runner. The step can be
        executed directly on the current machine or inside the docker. Results of the step can be cached. The caching
        is mostly aimed to reduce build time on the CI/CD such as GitHub Actions. In order to achieve desired caching
        behaviour, all input data, that can affect the result, has to be taken into account.
        For now, such data is:
            - files which are used during steps run.
            - environment variables which are passed to steps script.
        All this data is used to calculate the checksum of the step and assign it as a unique id which can be used as
            GitHub Actions cache key.
    """

    def __init__(
        self,
        name: str,
        script_path: Union[pl.Path, str],
        tracked_files_globs: List[Union[str, pl.Path]] = None,
        base: Union["EnvironmentRunnerStep", DockerImageSpec] = None,
        required_steps: Dict[str, "ArtifactRunnerStep"] = None,
        environment_variables: Dict[str, str] = None,
        github_actions_settings: "GitHubActionsSettings" = None,
    ):
        """
        :param name: Name of the step.
        :param script_path: Path of the shell or Python script which has to be executed by step.
        :param tracked_files_globs: List of file paths or globs to track their content while calculating cache key for
            a step.
        :param base: Another 'EnvironmentRunnerStep' or docker image that will be used as base environment where this
            step will run.
        :param required_steps: List of other steps that has to be executed in order to run this step.
        :param environment_variables: Dist with environment variables to pass to step's script.
        :param github_actions_settings: Additional setting on how step has to be executed on GitHub Actions CI/CD
        """
        self.name = name
        script_path = pl.Path(script_path)
        if script_path.is_absolute():
            script_path = script_path.relative_to(SOURCE_ROOT)
        self.script_path = script_path

        tracked_files_globs = tracked_files_globs or []
        # Also add script path and shell helper script to tracked files list.
        tracked_files_globs.extend(
            [
                self.script_path,
                "agent_build_refactored/tools/steps_libs/step_runner.sh",
            ]
        )
        self.tracked_files_globs = tracked_files_globs
        self._tracked_files = self._get_tracked_files(tracked_files_globs)

        self.required_steps = required_steps or {}
        self.environment_variables = environment_variables or {}

        if isinstance(base, EnvironmentRunnerStep):
            # The previous step is specified.
            # The base docker image is a result image of the previous step.
            self._base_docker_image = base.result_image
            self.initial_docker_image = base.initial_docker_image
            self._base_step = base
        elif isinstance(base, DockerImageSpec):
            # The previous step isn't specified, but it is just a docker image.
            self._base_docker_image = base
            self.initial_docker_image = base
            self._base_step = None
        else:
            # the previous step is not specified.
            self._base_docker_image = None
            self.initial_docker_image = None
            self._base_step = None

        self.runs_in_docker = bool(self.initial_docker_image)

        self.github_actions_settings = (
            github_actions_settings or GitHubActionsSettings()
        )

        self.checksum = self._calculate_checksum()

        self.id = self._get_id()

        if self.runs_in_docker:
            _step_container_name = f"{self.result_image.name}-container".replace(
                ":", "-"
            )
        else:
            _step_container_name = None

        self._step_container_name = _step_container_name

    @staticmethod
    def _get_tracked_files(tracked_files_globs: List[pl.Path]) -> List[pl.Path]:
        """
        Resolve steps tracked files globs into final list of files.
        """
        tracked_file_globs = [pl.Path(g) for g in tracked_files_globs]
        # All final file paths to track.
        tracked_files = []

        # Resolve file globs to get all files to track.
        for file_glob in set(tracked_file_globs):
            file_glob = pl.Path(file_glob)

            if file_glob.is_absolute():
                if not str(file_glob).startswith(str(SOURCE_ROOT)):
                    raise ValueError(
                        f"Tracked file glob {file_glob} is not part of the source {SOURCE_ROOT}"
                    )

                file_glob = file_glob.relative_to(SOURCE_ROOT)

            found = list(SOURCE_ROOT.glob(str(file_glob)))

            tracked_files.extend(found)

        return sorted(list(set(tracked_files)))

    def get_all_cacheable_steps(self) -> List["RunnerStep"]:
        """
        Get list of all steps (including nested) which are used by this step.
        """
        result = []

        # Include current step itself, if needed.
        if self.github_actions_settings.cacheable:
            result.append(self)

        for step in self.required_steps.values():
            result.extend(step.get_all_cacheable_steps())

        if self._base_step:
            result.extend(self._base_step.get_all_cacheable_steps())

        return result

    def _get_id(self) -> str:
        """
        Unique (suppose to be) identifier of the step.
        Its format - "<step_name>-<docker_image_name>-<docker-image-platform>-<step-checksum>".
        If step does not run in docker, then docker related part are excluded.
        """
        result = f"{self.name}"
        if self.runs_in_docker:
            image_name = self.initial_docker_image.name.replace(":", "-")
            image_platform = self.initial_docker_image.platform.to_dashed_str
            result = f"{result}-{image_name}-{image_platform}"
        result = f"{result}-{self.checksum}"
        return result

    @property
    def result_image(self) -> Optional[DockerImageSpec]:
        """
        The spec of the result docker image.
        """
        if not self.runs_in_docker:
            return None

        return DockerImageSpec(
            # Image name just the same as id.
            name=self.id,
            platform=self._base_docker_image.platform,
        )

    def get_output_directory(self, work_dir: pl.Path):
        return work_dir / "step_output" / self.id

    def get_cache_directory(self, work_dir: pl.Path):
        return work_dir / "step_cache" / self.id

    def get_isolated_root(self, work_dir: pl.Path):
        return work_dir / "step_isolated_root" / self.id

    def _get_required_steps_output_directories(
        self, work_dir: pl.Path
    ) -> Dict[str, pl.Path]:
        """
        Return path of the outputs of all steps which are required by this step.
        """
        result = {}

        for step_env_var_name, step in self.required_steps.items():
            step_out_dir = step.get_output_directory(work_dir=work_dir)
            if self.runs_in_docker:
                step_out_dir = step_out_dir.name
                step_dir = pl.Path("/tmp/required_steps") / step_out_dir
            else:
                step_dir = step_out_dir

            result[step_env_var_name] = step_dir

        return result

    def _get_all_environment_variables(self, work_dir: pl.Path):
        """Gather and return all environment variables that has to be passed to step's script."""
        result_env_variables = UniqueDict()

        req_steps_env_variables = self._get_required_steps_output_directories(
            work_dir=work_dir
        )
        # Set path of the required steps as env. variables.
        for step_env_var_name, step_output_path in req_steps_env_variables.items():
            result_env_variables[step_env_var_name] = str(step_output_path)

        result_env_variables.update(self.environment_variables)

        if IN_CICD:
            result_env_variables["IN_CICD"] = "1"

        return result_env_variables

    def _calculate_checksum(self) -> str:
        """
        The checksum of the step. It takes into account all input data that step accepts and also
            all checksums of all other steps which are used by this step.
        """

        sha256 = hashlib.sha256()

        # Add checksums of the required steps.
        for step in self.required_steps.values():
            sha256.update(step.checksum.encode())

        # Add base step's checksum.
        if self._base_step:
            sha256.update(self._base_step.checksum.encode())

        # Add checksums of environment variables.
        for name, value in self.environment_variables.items():
            sha256.update(name.encode())
            sha256.update(value.encode())

        # Calculate the sha256 for each file's content, filename.
        for file_path in self._tracked_files:
            sha256.update(str(file_path.relative_to(SOURCE_ROOT)).encode())
            sha256.update(file_path.read_bytes())

        return sha256.hexdigest()

    @staticmethod
    def _remove_output_directory(output_directory: pl.Path):
        if output_directory.is_dir():
            remove_directory_in_docker(output_directory)
        elif output_directory.is_symlink():
            output_directory.unlink()

    def _restore_cache(
        self, output_directory: pl.Path, cache_directory: pl.Path
    ) -> bool:
        """
        Searches for cached results, if found, then they are reused and the run is skipped.
        :return: Boolean that indicates that the cache is found and step can be skipped.
        """
        pass

    def _save_to_cache(
        self, is_skipped: bool, output_directory: pl.Path, cache_directory: pl.Path
    ):
        """
        Saved results of the finished step to cache, if needed.
        :param is_skipped: Boolean flag that indicates that the main run method has been skipped.
        """
        pass

    def _pre_run(self) -> bool:
        """Function that runs after the step main run function."""
        pass

    def _post_run(self):
        """
        Function that runs after the step main run function.
        """
        pass

    def _run_script(
        self,
        work_dir: pl.Path,
    ):
        """
        Run the step's script, whether in docker or in current system.
        """

        isolated_source_root = self.get_isolated_root(work_dir=work_dir)
        cache_directory = self.get_cache_directory(work_dir=work_dir)
        output_directory = self.get_output_directory(work_dir=work_dir)

        if self.runs_in_docker:
            final_isolated_source_root = pl.Path("/tmp/agent_source")
            final_cache_directory = "/tmp/step_cache"
            final_output_directory = "/tmp/step_output"
        else:
            final_isolated_source_root = isolated_source_root
            final_cache_directory = cache_directory
            final_output_directory = output_directory

        if self.script_path.suffix == ".py":
            script_type = "python"
        else:
            script_type = "shell"

        command_args = [
            "env",
            "bash",
            # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
            # and also provides some helper functions such as caching.
            "agent_build_refactored/tools/steps_libs/step_runner.sh",
            str(self.script_path),
            str(final_cache_directory),
            str(final_output_directory),
            script_type,
        ]

        env_variables_to_pass = self._get_all_environment_variables(work_dir=work_dir)

        # Run step directly on the current system
        if not self.runs_in_docker:
            env = os.environ.copy()

            python_path = env.get("PYTHONPATH", "")
            for p in python_path.split(os.pathsep):
                p = pl.Path(p)
                if not str(p).startswith(str(SOURCE_ROOT)):
                    continue
                new_p = isolated_source_root / p.relative_to(SOURCE_ROOT)
                python_path = python_path.replace(str(p), str(new_p))

            python_path = f"{python_path}{os.pathsep}{isolated_source_root}"
            env["PYTHONPATH"] = python_path

            env.update(env_variables_to_pass)
            check_call_with_log(command_args, env=env, cwd=str(isolated_source_root))
            return

        # Run step in docker.
        check_call_with_log(["docker", "rm", "-f", self._step_container_name])

        required_steps_directories = self._get_required_steps_output_directories(
            work_dir=work_dir
        )
        mount_options = []
        for step_env_var_name, step_output_path in required_steps_directories.items():
            mount_options.extend(["-v", f"{output_directory}:{step_output_path}"])

        # Mount isolated source root, output path and cache to be able to use them later.
        mount_options.extend(
            [
                "-v",
                f"{isolated_source_root}:{final_isolated_source_root}",
                "-v",
                f"{cache_directory}:{final_cache_directory}",
                "-v",
                f"{output_directory}:{final_output_directory}",
            ]
        )

        env_options = []
        for env_var_name, env_var_val in env_variables_to_pass.items():
            env_options.extend(["-e", f"{env_var_name}={env_var_val}"])

        check_call_with_log(
            [
                "docker",
                "run",
                "-i",
                "--name",
                self._step_container_name,
                "--workdir",
                str(final_isolated_source_root),
                *mount_options,
                *env_options,
                self._base_docker_image.name,
                *command_args,
            ]
        )

    def run(self, work_dir: pl.Path):
        """
        Run the step. Based on its initial data, it will be executed in docker or locally, on the current system.
        """

        output_directory = self.get_output_directory(work_dir)
        cache_directory = self.get_cache_directory(work_dir)
        isolated_source_root = self.get_isolated_root(work_dir)

        output_directory.parent.mkdir(parents=True, exist_ok=True)
        skipped = self._restore_cache(
            output_directory=output_directory, cache_directory=cache_directory
        )
        if skipped:
            log.info(f"Result of the step '{self.id}' is found in cache, skip.")
            return

        logging.info(f"Run step {self.name}.")
        for step in self.required_steps.values():
            step.run(work_dir=work_dir)

        if self._base_step:
            self._base_step.run(work_dir=work_dir)

        self._remove_output_directory(output_directory=output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)

        # Create directory to store only tracked files.
        if isolated_source_root.exists():
            shutil.rmtree(isolated_source_root)
        isolated_source_root.mkdir(parents=True)

        # Copy all tracked files into a new isolated directory.
        for file_path in self._tracked_files:
            dest_path = isolated_source_root / file_path.parent.relative_to(SOURCE_ROOT)
            dest_path.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest_path)

        all_env_variables = self._get_all_environment_variables(work_dir=work_dir)
        env_variables_str = "\n    ".join(
            f"{n}='{v}'" for n, v in all_env_variables.items()
        )
        logging.info(
            f"Start step: {self.id}\n"
            f"Passed env. variables:\n    {env_variables_str}\n"
        )
        try:
            self._run_script(work_dir=work_dir)
        except Exception:
            files = [str(g) for g in self._tracked_files]
            logging.exception(
                f"'{type(self).__name__}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {files}."
            )
            raise
        finally:
            self.cleanup()

        self._save_to_cache(
            is_skipped=skipped,
            output_directory=output_directory,
            cache_directory=cache_directory,
        )

    def cleanup(self):
        if self._step_container_name:
            check_call_with_log(["docker", "rm", "-f", self._step_container_name])

    def __eq__(self, other: "RunnerStep"):
        return self.id == other.id


class ArtifactRunnerStep(RunnerStep):
    """
    Specialised step which produces some artifact as a result of its execution.
    """

    def _restore_cache(
        self, output_directory: pl.Path, cache_directory: pl.Path
    ) -> bool:
        self._remove_output_directory(output_directory=output_directory)

        if cache_directory.exists():

            output_directory.symlink_to(cache_directory)
            return True

        return False

    def _save_to_cache(
        self, is_skipped: bool, output_directory: pl.Path, cache_directory: pl.Path
    ):
        if not is_skipped:
            shutil.copytree(output_directory, cache_directory, dirs_exist_ok=True)


class EnvironmentRunnerStep(RunnerStep):
    """
    Specialised step which performs some actions on some environment in order to prepare if for further uses.
        If this step runs in docker, it performs its actions inside specified base docker image and produces
        new image with the result environment.
        If step does not run in docker, then its actions are executed directly on current system.
    """

    def _restore_cache(
        self, output_directory: pl.Path, cache_directory: pl.Path
    ) -> bool:
        if not self.runs_in_docker:
            return False

        # Before the run, check if there is already an image with the same name. The name contains the checksum
        # of all files which are used in it, so the name identity also guarantees the content identity.
        output_bytes = check_output_with_log(
            ["docker", "images", "-q", self.result_image.name]
        )
        output = output_bytes.decode().strip()

        if output:
            # The image already exists, skip the run.
            logging.info(
                f"Image '{self.result_image.name}' already exists, skip and reuse it."
            )
            return True

        # # If code runs in CI/CD, then check if the image file is already in cache, and we can reuse it.
        # if common.IN_CICD:

        # Check in step's cache for the image tarball.
        cached_image_path = cache_directory / self.result_image.name
        if cached_image_path.is_file():
            logging.info(
                f"Cached image {self.result_image.name} file for the step '{self.name}' has been found, "
                f"loading and reusing it instead of building."
            )
            check_call_with_log(["docker", "load", "-i", str(cached_image_path)])
            return True

        return False

    def _save_to_cache(
        self, is_skipped: bool, output_directory: pl.Path, cache_directory: pl.Path
    ):
        # Save results in cache if needed.
        if not self.runs_in_docker or is_skipped:
            return
        check_call_with_log(
            ["docker", "commit", self._step_container_name, self.result_image.name]
        )
        cache_directory.mkdir(parents=True, exist_ok=True)
        cached_image_path = cache_directory / self.result_image.name
        logging.info(
            f"Saving image '{self.result_image.name}' file for the step {self.name} into cache."
        )
        self.result_image.save_docker_image(output_path=cached_image_path)


class Runner:
    """
    Abstraction which combines several RunnerStep instances in order to execute them and to use their results
        in order to perform its own work.
    """

    # List of Runner steps which are required by this Runner. All steps which are meant to be cached by GitHub Actions
    # have to be specified here.
    REQUIRED_STEPS: List[RunnerStep] = []

    # List of other Runner classes that are required by this one. As with previous, runners, which steps have to be
    # cached by GitHub Actions, have to be specified here.
    REQUIRED_RUNNERS_CLASSES: List[Type["Runner"]] = []

    # Base environment step. Runner runs on top of it. Can be a docker image, so the Runner will be executed in
    # container.
    BASE_ENVIRONMENT: Union[EnvironmentRunnerStep, str] = None

    # This class attribute is used to find and load this runner class without direct access to it.
    _FULLY_QUALIFIED_NAME = None

    def __init__(
        self,
        work_dir: pl.Path,
        required_steps: List[RunnerStep] = None,
    ):
        """
        :param work_dir: Path to the directory where Runner will store its results and intermediate data.
        :param required_steps: Final list of RunnerSteps to be executed by this runner. If not specified, then just
            the `REQUIRED_STEPS` class attribute is used.
        """

        self.base_environment = type(self).BASE_ENVIRONMENT
        self.required_steps = required_steps or type(self).REQUIRED_STEPS[:]
        self.required_runners = {}

        self.work_dir = work_dir
        output_name = type(self).get_fully_qualified_name().replace(".", "_")
        self.output_path = work_dir / "runner_outputs" / output_name

        self._input_values = {}

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        return cls.REQUIRED_STEPS[:]

    @classmethod
    def get_all_cacheable_steps(cls) -> List[RunnerStep]:
        """
        Gather all (including nested) RunnerSteps from all possible plases which are used by this runner.
        """
        result = []

        if cls.BASE_ENVIRONMENT:
            result.extend(cls.BASE_ENVIRONMENT.get_all_cacheable_steps())

        for req_step in cls.get_all_required_steps():
            result.extend(req_step.get_all_cacheable_steps())

        for runner_clas in cls.REQUIRED_RUNNERS_CLASSES:
            result.extend(runner_clas.get_all_cacheable_steps())

        return result

    @classmethod
    def get_fully_qualified_name(cls) -> str:
        """
        Return fully qualified name of the class. This is needed for the runner to be able to run itself from
        other process or docker container. We have a special script 'agent_build/scripts/runner_helper.py' which
        can execute runner through finding them by their FQDN.
        """

        if cls._FULLY_QUALIFIED_NAME:
            return cls._FULLY_QUALIFIED_NAME

        return f"{cls.__module__}.{cls.__qualname__}"

    @classmethod
    def assign_fully_qualified_name(
        cls,
        class_name: str,
        module_name: str,
        class_name_suffix: str = "",
    ):
        """
        If runner class is created dynamically, and does not exist by default in the global scope,
            then this method can do a little trick by creating an alias attribute of this class in target module.
        :param class_name: Name of the result class.
        :param class_name_suffix: Additional suffix to class name. if needed.
        :param module_name: Name of the module where to add an attribute with this class.
        """
        final_class_name = f"{class_name}{class_name_suffix}"

        module = sys.modules[module_name]
        if module_name == "__main__":
            # if the module is main we still have to get its full name

            module_file_path = pl.Path(module.__file__)
            if module_file_path.is_absolute():
                module_file_path = module_file_path.relative_to(SOURCE_ROOT)

            module_name_parts = str(module_file_path).strip(".py").split(os.sep)
            module_name = ".".join(module_name_parts)

        # Assign class' new alias in the target module to its FQDN.
        cls._FULLY_QUALIFIED_NAME = f"{module_name}.{final_class_name}"
        cls.__name__ = final_class_name

        # Create alias attribute in the target module.
        if hasattr(module, final_class_name):
            raise ValueError(
                f"Attribute '{final_class_name}' of the module {module_name} is already set."
            )

        setattr(module, final_class_name, cls)

    def run(self):
        """
        Function where Runner performs its main actions.
        """

        # Cleanup output if needed.
        if self.output_path.is_dir():
            remove_directory_in_docker(self.output_path)
        self.output_path.mkdir(parents=True)

        # Determine if Runner has to run in docker.
        docker_image = None
        if self.base_environment:
            # If base environment is EnvironmentStep, then use its result docker image as base environment.
            if isinstance(self.base_environment, EnvironmentRunnerStep):
                if self.base_environment.runs_in_docker:
                    docker_image = self.base_environment.result_image
            else:
                # It has to be a DockerImageSpec, so execute the runner inside the environment specified in image spec.
                docker_image = self.base_environment

        # Run all steps and runners we depend on, skip this if we already in docker to avoid infinite loop.
        if not IN_DOCKER:
            if self.base_environment:
                self.base_environment.run(work_dir=self.work_dir)

            for required_step in self.get_all_required_steps():
                required_step.run(work_dir=self.work_dir)

            if self.required_runners:
                for runner in self.required_runners:
                    runner.run(work_dir=self.work_dir)

        # If runner does not run in docker just run it directly.
        if not docker_image:
            self._run()
            return

        # This runner runs in docker. Make docker container run special script which has to run
        # the same runner. The runner has to be found by its FQDN.
        command_args = [
            "python3",
            "/scalyr-agent-2/agent_build_refactored/scripts/runner_helper.py",
            self.get_fully_qualified_name(),
        ]

        # To run exactly the same runner inside the docker, we have to pass exactly the same arguments.
        # We can do this because we already saved constructor arguments of this particular instance in
        # its 'self.input_values' attribute.
        # We go through constructor's signature, get appropriate constructor argument values and create
        # command line arguments.
        signature = inspect.signature(self.__init__)

        additional_mounts = []
        for name, param in signature.parameters.items():
            value = self.input_values[name]

            if value is None:
                continue

            if isinstance(value, (str, pl.Path)):
                path = pl.Path(value)
                # if value represents path, them also mount this path to a container.
                if path.exists() and not str(path).startswith(str(SOURCE_ROOT)):
                    docker_path = pl.Path("/tmp/other_mounts/") / path.relative_to("/")
                    additional_mounts.extend(["-v", f"{path}:{docker_path}"])
                    value = docker_path

            command_args.extend([f"--{name}".replace("_", "-"), str(value)])

        env_options = [
            "-e",
            "AGENT_BUILD_IN_DOCKER=1",
        ]

        if IN_CICD:
            env_options.extend(["-e", "IN_CICD=1"])

        # Finally execute runner with generated command line arguments in container.
        check_call_with_log(
            [
                "docker",
                "run",
                "-i",
                "--rm",
                "-v",
                f"{SOURCE_ROOT}:/scalyr-agent-2",
                *additional_mounts,
                *env_options,
                docker_image.name,
                *command_args,
            ]
        )

    def _run(self):
        """
        Function where Runners main work is executed.
        """
        pass

    @classmethod
    def _get_command_line_functions(cls):
        result = {}
        for m_name, value in inspect.getmembers(cls):
            if hasattr(value, "is_cli_command"):
                result[m_name] = value

        return result

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        """
        Create argparse parser with all arguments which are generated from constructor's signature.
        """

        parser.add_argument(
            "--get-all-cacheable-steps",
            dest="get_all_cacheable_steps",
            action="store_true",
            help="Get ids of all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
            "use it manually.",
        )

        parser.add_argument(
            "--run-all-cacheable-steps",
            dest="run_all_cacheable_steps",
            action="store_true",
            help="Run all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
            "use it manually.",
        )

        parser.add_argument(
            "--work-dir",
            dest="work_dir",
            default=str(SOURCE_ROOT / "agent_build_output"),
            help="Directory path where all final and intermediate results are store, maybe helpful during debugging.",
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        """
        Handle parsed command line arguments and perform needed actions.
        """
        if args.get_all_cacheable_steps:
            steps = cls.get_all_cacheable_steps()
            steps_ids = [step.id for step in steps]
            print(json.dumps(steps_ids))
            exit(0)

        work_dir = pl.Path(args.work_dir)

        if args.run_all_cacheable_steps:
            steps = cls.get_all_cacheable_steps()
            for step in steps:
                step.run(work_dir=work_dir)
            exit(0)
