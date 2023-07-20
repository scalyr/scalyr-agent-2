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
import hashlib
import json
import os
import pathlib as pl
import shutil
import logging
import inspect
import subprocess
import sys
from typing import Union, Optional, List, Dict, Type, Callable


from agent_build_refactored.tools.constants import (
    SOURCE_ROOT,
    DockerPlatformInfo,
    Architecture,
    IN_CICD,
)
from agent_build_refactored.tools import (
    check_call_with_log,
    check_output_with_log_debug,
    DockerContainer,
    UniqueDict,
    IN_DOCKER,
)

from agent_build_refactored.tools.run_in_ec2.constants import EC2DistroImage

logger = logging.getLogger(__name__)


def remove_directory_in_docker(path: pl.Path):
    """
    Since we produce some artifacts inside docker containers, we may face difficulties with
    deleting the old ones because they may be created inside the container with the root user.
    The workaround for that to delegate that deletion to a docker container as well.
    """

    if IN_DOCKER:
        shutil.rmtree(path)
        return

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

    def save_docker_image(self, output_path: pl.Path, remote_docker_host: str = None):
        """
        Serialize docker image into file by using 'docker save' command.
        :param output_path: Result output file.
        :param remote_docker_host: String with remote docker engine.
        """
        run_docker_command(
            ["save", self.name, "--output", str(output_path)],
            remote_docker_host=remote_docker_host,
        )


@dataclasses.dataclass
class GitHubActionsSettings:
    """Dataclass that stores settings for how step has to be executed on GitHub Actions CI/CD"""

    # Flag that indicates that step has to be cached by GHA CI/CD
    cacheable: bool = False

    # Flag that indicates that this step has to be executed in a separate job during GHA CI/CD run.
    # In case of multiple, long-running steps, this has to decrease overall build time.
    pre_build_in_separate_job: bool = False
    run_in_remote_docker: bool = False


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
        user: str = "root",
        github_actions_settings: "GitHubActionsSettings" = None,
    ):
        """
        :param name: Name of the step.
        :param script_path: Path of the shell or Python script which has to be executed by step.
        :param tracked_files_globs: List of file paths or globs to track their content while calculating cache key for
            a step.
        :param base: Another 'EnvironmentRunnerStep' or docker image that will be used as base environment where this
            step will run.
        :param required_steps: Collection (dict) of other steps that has to be executed in order to run this step.
            Key - Name of the env. variable that points to step's output directory with it;s result artifacts.
            Value - Step instance.
        :param environment_variables: Dist with environment variables to pass to step's script.
        :param user: Name of the user under which name run the step's script.
        :param github_actions_settings: Additional setting on how step has to be executed on GitHub Actions CI/CD
        """
        self.name = name
        self.user = user
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
            self.architecture = base.architecture
        elif isinstance(base, DockerImageSpec):
            # The previous step isn't specified, but it is just a docker image.
            self._base_docker_image = base
            self.initial_docker_image = base
            self._base_step = None
            self.architecture = self.initial_docker_image.platform.as_architecture
        else:
            # the previous step is not specified.
            self._base_docker_image = None
            self.initial_docker_image = None
            self._base_step = None
            self.architecture = Architecture.UNKNOWN

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

            filtered = []
            for path in found:
                if path.is_dir():
                    continue

                skip = False
                for to_ignore in ["__pycache__", ".pytest_cache", ".DS_Store"]:
                    if to_ignore in path.parent.parts:
                        skip = True
                        break

                if skip:
                    continue

                filtered.append(path)

            tracked_files.extend(filtered)

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
            image_name = image_name.replace(".", "-")
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
            result[step_env_var_name] = step.get_output_directory(work_dir=work_dir)

        return result

    def _get_required_steps_docker_output_directories(
        self, work_dir: pl.Path
    ) -> Dict[str, pl.Path]:
        """
        Return path of the docker outputs of all steps which are required by this step.
        """
        result = {}

        for step_env_var_name, step in self.required_steps.items():
            step_out_dir = step.get_output_directory(work_dir=work_dir)
            step_dir = pl.Path("/tmp") / f"required_step_{step_out_dir.name}"
            result[step_env_var_name] = step_dir

        return result

    def _get_all_environment_variables(self, work_dir: pl.Path):
        """Gather and return all environment variables that has to be passed to step's script."""
        result_env_variables = UniqueDict()

        if self.runs_in_docker:
            req_steps_env_variables = (
                self._get_required_steps_docker_output_directories(work_dir=work_dir)
            )
        else:
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
            # Include file's path...
            sha256.update(str(file_path.relative_to(SOURCE_ROOT)).encode())
            # ... content ...
            sha256.update(file_path.read_bytes())
            # ... and permissions.
            sha256.update(str(file_path.stat().st_mode).encode())

        # Also add user into the checksum.
        sha256.update(self.user.encode())

        if self.runs_in_docker:
            sha256.update(self.initial_docker_image.name.encode())
            sha256.update(self.initial_docker_image.platform.to_dashed_str.encode())

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
        if cache_directory.exists():
            if output_directory.exists():
                if output_directory.is_symlink():
                    output_directory.unlink()
                else:
                    remove_directory_in_docker(output_directory)

            symlink_rel_path = pl.Path("../step_cache") / output_directory.name
            output_directory.symlink_to(symlink_rel_path)
            return True

        return False

    def _save_to_cache(
        self, is_skipped: bool, output_directory: pl.Path, cache_directory: pl.Path
    ):
        """
        Saved results of the finished step to cache, if needed.
        :param is_skipped: Boolean flag that indicates that the main run method has been skipped.
        """
        if not is_skipped:
            shutil.copytree(
                output_directory, cache_directory, dirs_exist_ok=True, symlinks=True
            )

    def _pre_run(self) -> bool:
        """Function that runs after the step main run function."""
        pass

    def _post_run(self):
        """
        Function that runs after the step main run function.
        """
        pass

    def _run_script_locally(
        self,
        work_dir: pl.Path,
    ):
        """
        Run the step's script, whether in docker or in current system.
        :param work_dir: Path to directory where all results are stored.
        """

        isolated_source_root = self.get_isolated_root(work_dir=work_dir)
        isolated_source_root.mkdir(parents=True, exist_ok=True)
        cache_directory = self.get_cache_directory(work_dir=work_dir)
        cache_directory.mkdir(parents=True, exist_ok=True)
        output_directory = self.get_output_directory(work_dir=work_dir)
        output_directory.mkdir(parents=True, exist_ok=True)

        env_variables_to_pass = self._get_all_environment_variables(work_dir=work_dir)

        env = os.environ.copy()
        env.update(env_variables_to_pass)

        command_args = self._get_command_args(
            cache_directory=cache_directory, output_directory=output_directory
        )

        check_call_with_log(command_args, env=env, cwd=str(isolated_source_root))

    def _run_script_in_docker(self, work_dir: pl.Path, remote_docker_host: str):
        """
        Run runner step's script in docker.
        :param work_dir: Path to directory where all results are stored.
        :param remote_docker_host: If not None - host of the remote docker machine to execute script.
        """

        isolated_source_root = self.get_isolated_root(work_dir=work_dir)
        cache_directory = self.get_cache_directory(work_dir=work_dir)
        output_directory = self.get_output_directory(work_dir=work_dir)

        in_docker_isolated_source_root = pl.Path("/tmp/agent_source")
        in_docker_cache_directory = pl.Path("/tmp/step_cache")
        in_docker_output_directory = pl.Path("/tmp/step_output")

        # Run step in docker.
        required_steps_directories = self._get_required_steps_output_directories(
            work_dir=work_dir
        )
        required_steps_docker_directories = (
            self._get_required_steps_docker_output_directories(work_dir=work_dir)
        )

        required_step_mounts = {}
        for step_env_var_name, step_output_path in required_steps_directories.items():
            step_docker_output_path = required_steps_docker_directories[
                step_env_var_name
            ]
            required_step_mounts[step_output_path] = step_docker_output_path

        env_variables_to_pass = self._get_all_environment_variables(work_dir=work_dir)

        env_options = []
        for env_var_name, env_var_val in env_variables_to_pass.items():
            env_options.extend(["-e", f"{env_var_name}={env_var_val}"])

        if self._base_step is not None:
            base_output_directory = self._base_step.get_output_directory(
                work_dir=work_dir
            )
            image_path = base_output_directory / self._base_docker_image.name
            # Load base image.
            _load_image(
                image_name=self._base_docker_image.name,
                image_path=image_path,
                remote_docker_host=remote_docker_host,
            )

        run_docker_command(
            ["rm", "-f", self._step_container_name],
            remote_docker_host=remote_docker_host,
        )

        command_args = self._get_command_args(
            cache_directory=in_docker_cache_directory,
            output_directory=in_docker_output_directory,
        )

        # Create intermediate container
        run_docker_command(
            ["rm", "-f", self._step_container_name],
            remote_docker_host=remote_docker_host,
        )

        run_docker_command(
            [
                "create",
                "--name",
                self._step_container_name,
                "--workdir",
                str(in_docker_isolated_source_root),
                "--user",
                self.user,
                "--platform",
                str(self.architecture.as_docker_platform.value),
                *env_options,
                self._base_docker_image.name,
                *command_args,
            ],
            remote_docker_host=remote_docker_host,
        )

        # Instead of mounting we have to copy files to an intermediate container,
        # because mounts does not work with remote docker.
        input_paths = {
            f"{isolated_source_root}/.": in_docker_isolated_source_root,
            **{f"{src}/.": dst for src, dst in required_step_mounts.items()},
            f"{output_directory}/.": in_docker_output_directory,
            f"{cache_directory}/.": in_docker_cache_directory,
        }

        for src, dst in input_paths.items():
            run_docker_command(
                ["cp", "-a", "-L", str(src), f"{self._step_container_name}:{dst}"],
                remote_docker_host=remote_docker_host,
            )

        run_docker_command(
            [
                "start",
                "-i",
                self._step_container_name,
            ],
            remote_docker_host=remote_docker_host,
        )

        output_paths = {
            f"{in_docker_output_directory}/.": output_directory,
            f"{in_docker_cache_directory}/.": cache_directory,
        }

        for src, dst in output_paths.items():
            run_docker_command(
                [
                    "cp",
                    "-a",
                    f"{self._step_container_name}:/{src}",
                    str(dst),
                ],
                remote_docker_host=remote_docker_host,
            )

    def _get_command_args(self, cache_directory: pl.Path, output_directory: pl.Path):
        """
        Get list with command arguments that has to be executed by step.
        :return:
        """
        if self.script_path.suffix == ".py":
            script_type = "python"
        else:
            script_type = "shell"

        return [
            "env",
            "bash",
            # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
            # and also provides some helper functions such as caching.
            "agent_build_refactored/tools/steps_libs/step_runner.sh",
            str(self.script_path),
            str(cache_directory),
            str(output_directory),
            script_type,
        ]

    def run(
        self,
        work_dir: pl.Path,
        remote_docker_host_getter: Callable[["RunnerStep"], str] = None,
    ):
        """
        Run the step. Based on its initial data, it will be executed in docker or locally, on the current system.
        """

        output_directory = self.get_output_directory(work_dir)
        cache_directory = self.get_cache_directory(work_dir)
        isolated_source_root = self.get_isolated_root(work_dir)

        output_directory.parent.mkdir(parents=True, exist_ok=True)
        cache_directory.parent.mkdir(parents=True, exist_ok=True)

        skipped = self._restore_cache(
            output_directory=output_directory, cache_directory=cache_directory
        )
        if skipped:
            logger.info(f"Result of the step '{self.id}' is found in cache, skip.")
            return

        logging.info(f"Run step {self.name}.")
        for step in self.required_steps.values():
            step.run(
                work_dir=work_dir, remote_docker_host_getter=remote_docker_host_getter
            )

        if self._base_step:
            self._base_step.run(
                work_dir=work_dir, remote_docker_host_getter=remote_docker_host_getter
            )

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

        self.get_isolated_root(work_dir=work_dir).mkdir(parents=True, exist_ok=True)
        self.get_cache_directory(work_dir=work_dir).mkdir(parents=True, exist_ok=True)
        self.get_output_directory(work_dir=work_dir).mkdir(parents=True, exist_ok=True)

        try:
            if self.runs_in_docker:
                remote_docker_host = remote_docker_host_getter(self)
                self._run_script_in_docker(
                    work_dir=work_dir, remote_docker_host=remote_docker_host
                )
            else:
                self._run_script_locally(work_dir=work_dir)
        except Exception:
            files = [str(g) for g in self._tracked_files]
            logging.exception(
                f"'{self.name}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {files}."
            )
            raise

        self._save_to_cache(
            is_skipped=skipped,
            output_directory=output_directory,
            cache_directory=cache_directory,
        )
        self.cleanup()

    def cleanup(self):
        if self._step_container_name:
            run_docker_command(["rm", "-f", self._step_container_name])

    def __eq__(self, other: "RunnerStep"):
        return self.id == other.id


class ArtifactRunnerStep(RunnerStep):
    """
    Specialised step which produces some artifact as a result of its execution.
    """


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
        is_skipped = super(EnvironmentRunnerStep, self)._restore_cache(
            output_directory=output_directory, cache_directory=cache_directory
        )

        if self.runs_in_docker:
            return is_skipped

        return False

    def _run_script_in_docker(self, work_dir: pl.Path, remote_docker_host: str):
        """
        For the environment step, we also have to save result image.
        """

        super(EnvironmentRunnerStep, self)._run_script_in_docker(
            work_dir=work_dir, remote_docker_host=remote_docker_host
        )

        run_docker_command(
            ["commit", self._step_container_name, self.result_image.name],
            remote_docker_host=remote_docker_host,
        )

        output_directory = self.get_output_directory(work_dir=work_dir)
        image_path = output_directory / self.result_image.name

        logger.info(f"Saving image {self.result_image.name}.")
        if remote_docker_host:
            logger.info("    Saving from remote docker, it may take some time.")
        run_docker_command(
            ["save", self.result_image.name, "--output", str(image_path)],
            remote_docker_host=remote_docker_host,
        )


@dataclasses.dataclass
class RunnerMappedPath:
    path: Union[pl.Path, str]


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
        self, work_dir: pl.Path = None, required_steps: List[RunnerStep] = None
    ):
        """
        :param work_dir: Path to the directory where Runner will store its results and intermediate data.
        :param required_steps: Final list of RunnerSteps to be executed by this runner. If not specified, then just
            the `REQUIRED_STEPS` class attribute is used.
        """

        self.base_environment = type(self).get_base_environment()
        self.required_steps = required_steps or type(self).REQUIRED_STEPS[:]
        self.required_runners = {}

        self.work_dir = pl.Path(work_dir or SOURCE_ROOT / "agent_build_output")
        output_name = type(self).get_fully_qualified_name().replace(".", "_")
        self.output_path = self.work_dir / "runner_outputs" / output_name

        self._input_values = {}

    @classmethod
    def get_base_environment(cls) -> Optional[EnvironmentRunnerStep]:
        return cls.BASE_ENVIRONMENT

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        return cls.REQUIRED_STEPS[:]

    @classmethod
    def get_all_cacheable_steps(cls) -> List[RunnerStep]:
        """
        Gather all (including nested) RunnerSteps from all possible plases which are used by this runner.
        """
        result = []
        base_environment = cls.get_base_environment()
        if base_environment:
            result.extend(base_environment.get_all_cacheable_steps())

        for req_step in cls.get_all_required_steps():
            result.extend(req_step.get_all_cacheable_steps())

        for runner_clas in cls.REQUIRED_RUNNERS_CLASSES:
            result.extend(runner_clas.get_all_cacheable_steps())

        # Filter all identical steps
        result_dict = {step.id: step for step in result}
        return list(result_dict.values())

    @classmethod
    def get_fully_qualified_name(cls) -> str:
        """
        Return fully qualified name of the class. This is needed for the runner to be able to run itself from
        other process or docker container. We have a special script 'agent_build/scripts/runner_helper.py' which
        can execute runner through finding them by their FQDN.
        """

        if cls._FULLY_QUALIFIED_NAME:
            return cls._FULLY_QUALIFIED_NAME

        module_path = pl.Path(sys.modules[cls.__module__].__file__)
        module_rel_path = module_path.relative_to(SOURCE_ROOT)

        module_without_ext = module_rel_path.parent / module_rel_path.stem
        module_fqdn = str(module_without_ext).replace(os.sep, ".")
        return f"{module_fqdn}.{cls.__qualname__}"

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

    @property
    def base_docker_image(self) -> Optional[DockerImageSpec]:
        if self.base_environment:
            if isinstance(self.base_environment, DockerImageSpec):
                return self.base_environment

            # If base environment is EnvironmentStep, then use its result docker image as base environment.
            if self.base_environment.runs_in_docker:
                return self.base_environment.result_image

        return None

    @property
    def runs_in_docker(self) -> bool:
        return self.base_docker_image is not None and not IN_DOCKER

    def run_in_docker(
        self, command_args: List = None, python_executable: str = "python3"
    ):

        command_args = command_args or []

        final_command_args = []

        mount_args = []

        for arg in command_args:
            if not isinstance(arg, RunnerMappedPath):
                final_command_args.append(str(arg))
                continue

            path = pl.Path(arg.path)

            if path.is_absolute():
                path = path.relative_to("/")

            in_docker_path = pl.Path("/tmp/mounts") / path

            mount_args.extend(["-v", f"{arg.path}:{in_docker_path}"])
            final_command_args.append(str(in_docker_path))

        env_args = ["-e", "AGENT_BUILD_IN_DOCKER=1"]

        base_step_output = self.base_environment.get_output_directory(
            work_dir=self.work_dir
        )

        base_image_path = base_step_output / self.base_environment.result_image.name

        _load_image(
            image_name=self.base_environment.result_image.name,
            image_path=base_image_path,
        )

        run_docker_command(
            [
                "run",
                "-i",
                *mount_args,
                "-v",
                f"{SOURCE_ROOT}:/tmp/source",
                *env_args,
                "--platform",
                str(self.base_docker_image.platform),
                self.base_docker_image.name,
                python_executable,
                "/tmp/source/agent_build_refactored/scripts/runner_helper.py",
                type(self).get_fully_qualified_name(),
                *final_command_args,
            ]
        )

        # Run chmod for the output directory of the runner, in order to fix possible permission
        # error that can be due to using root user inside the docker.
        run_docker_command([
            "run",
            "-i",
            "--rm",
            "-v",
            f"{self.output_path}:/tmp/data",
            "ubuntu:22.04",
            "chown",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/tmp/data"
        ])

    def run_required(self):
        """
        Function where Runner performs its main actions.
        """

        # Cleanup output if needed.
        if self.output_path.is_dir():
            remove_directory_in_docker(self.output_path)
        self.output_path.mkdir(parents=True)

        # Run all steps and runners we depend on, skip this if we already in docker to avoid infinite loop.
        steps_to_run = []
        if not IN_DOCKER:
            if self.base_environment:
                steps_to_run.append(self.base_environment)

            steps_to_run.extend(self.get_all_required_steps())

            if self.required_runners:
                steps_to_run.extend(self.required_runners)

        self._run_steps(
            steps=steps_to_run,
            work_dir=self.work_dir,
        )

    def _run(self):
        """
        Function where Runners main work is executed.
        """
        pass

    @staticmethod
    def _run_steps(
        steps: List[RunnerStep],
        work_dir: pl.Path,
    ):
        """
        Run specified steps. If step is configured to run in remote docker engine (for example in remote ARM docker
            engine, to speed up build of the ARM packages)
        :param steps: List of steps to run.
        :param work_dir: Path to directory where all results are stored.
        """
        existing_ec2_hosts = {}
        existing_ec2_instances = []
        known_hosts_file = pl.Path.home() / ".ssh/known_hosts"

        def get_remote_docker_host_for_step(step: RunnerStep) -> Optional[str]:
            """
            Get host name of the remote docker engine where step has to be executed.
            If step is not configured to run in remote docker engine, then return None.
            """

            from agent_build_refactored.tools.run_in_ec2.boto3_tools import (
                create_and_deploy_ec2_instance,
                AWSSettings,
            )

            if not step.github_actions_settings.run_in_remote_docker:
                return None

            # Get EC2 AMI image according to step's architecture.
            ec2_image = DOCKER_EC2_BUILDERS.get(step.architecture)

            # Try to find already created node if it is created by previous steps.
            remote_docker_host = existing_ec2_hosts.get(step.architecture)

            if remote_docker_host is not None:
                return remote_docker_host

            # Create new remote docker engine EC2 node.
            aws_settings = AWSSettings.create_from_env()

            deployment_script_path = (
                SOURCE_ROOT
                / "agent_build_refactored/tools/run_in_ec2/deploy_docker_in_ec2_instance.sh"
            )

            boto3_session = aws_settings.create_boto3_session()

            instance = create_and_deploy_ec2_instance(
                boto3_session=boto3_session,
                aws_settings=aws_settings,
                name_prefix="remote_docker",
                ec2_image=ec2_image,
                root_volume_size=32,
                deployment_script=deployment_script_path,
            )

            instance_ip = instance.public_ip_address

            # We also have to add IP of the newly created server to known_hosts file.
            # Since we use remote docker engine by specifying the "DOCKER_HOST" env. variable,
            # it is not possible to specify additional SSH options such as 'StrictHostKeyChecking'
            # which is needed in order to connect to server, so we have to modify that file.
            new_known_host = subprocess.check_output(
                [
                    "ssh-keyscan",
                    "-H",
                    instance_ip,
                ],
            ).decode()

            known_hosts_file_content = f"{known_hosts_file_backup}\n{new_known_host}"
            known_hosts_file.write_text(known_hosts_file_content)

            existing_ec2_instances.append(instance)
            remote_docker_host = f"ssh://{ec2_image.ssh_username}@{instance_ip}"
            existing_ec2_hosts[step.architecture] = remote_docker_host
            return remote_docker_host

        known_hosts_file.parent.mkdir(parents=True, exist_ok=True)
        if known_hosts_file.exists():
            known_hosts_file_backup = known_hosts_file.read_text()
        else:
            known_hosts_file_backup = ""
        try:
            for s in steps:
                s.run(
                    work_dir=work_dir,
                    remote_docker_host_getter=get_remote_docker_host_for_step,
                )
        finally:
            # Restore original known_hosts file.
            known_hosts_file.write_text(known_hosts_file_backup)

            # Cleanup and destroy created instances.
            if existing_ec2_instances:
                for ins in existing_ec2_instances:
                    ins.terminate()

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

        cleanup()

        if args.get_all_cacheable_steps:
            steps = cls.get_all_cacheable_steps()
            steps_ids = [step.id for step in steps]
            print(json.dumps(steps_ids))
            exit(0)

        work_dir = pl.Path(args.work_dir)

        if args.run_all_cacheable_steps:
            steps = cls.get_all_cacheable_steps()

            cls._run_steps(
                steps=steps,
                work_dir=work_dir,
            )
            exit(0)

    def _start_ec2_builder_instance(self):
        pass


# Collection of EC2 AMI images that are used for creating instances with remote docker engine.
DOCKER_EC2_BUILDERS = {
    Architecture.ARM64: EC2DistroImage(
        image_id="ami-0e2b332e63c56bcb5",
        image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
        short_name="ubuntu2204_ARM",
        size_id="c7g.medium",
        ssh_username="ubuntu",
    )
}


def run_docker_command(
    command: List, remote_docker_host: str = None, return_output: bool = False
):
    """
    Run docker command.
    :param command: Command to run.
    :param remote_docker_host: Host name of the remote docker engine to execute command  within this engine.
    :param return_output: If true, return output of the command.
    """
    env = os.environ.copy()

    if remote_docker_host:
        env["DOCKER_HOST"] = remote_docker_host

    final_command = ["docker", *command]
    if return_output:
        return subprocess.check_output(final_command, env=env)

    subprocess.check_call(final_command, env=env)


def _load_image(image_name: str, image_path: pl.Path, remote_docker_host: str = None):
    """
    Load image from file, if needed.
    :param image_path: Image name, if presented in docker, then skip loading.
    :param image_name: Path to image file to load.
    :param remote_docker_host: Host name of the remote docker engine to execute command within this engine.
    """
    output_bytes = run_docker_command(
        ["images", "-q", image_name],
        remote_docker_host=remote_docker_host,
        return_output=True,
    )
    output = output_bytes.decode().strip()

    if output:
        logger.info(f"Image {image_name} is already in docker.")
        return

    logger.info(f"Loading image {image_name} from file {image_path}.")

    if remote_docker_host:
        logger.info("    Loading to remote host, it may take some time.")
    run_docker_command(
        ["load", "-i", str(image_path)], remote_docker_host=remote_docker_host
    )


def cleanup():
    if IN_DOCKER:
        return
    check_output_with_log_debug(["docker", "system", "prune", "-f", "--volumes"])
    check_output_with_log_debug(["docker", "system", "prune", "-f"])
