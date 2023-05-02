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


import abc
import argparse
import dataclasses
import hashlib
import json
import os
import pathlib as pl
import shlex
import shutil
import logging
import inspect
import subprocess
import sys
from typing import Union, Optional, List, Dict, Type, Callable, Iterable


from agent_build_refactored.tools.dependabot_aware_docker_images import UBUNTU_22_04
from agent_build_refactored.tools.constants import (
    SOURCE_ROOT,
    DockerPlatformInfo,
    Architecture,
    IN_CICD,
)
from agent_build_refactored.tools import (
    check_call_with_log,
    check_output_with_log_debug,
    UniqueDict,
    IN_DOCKER,
)

from agent_build_refactored.tools.run_in_ec2.constants import EC2DistroImage

logger = logging.getLogger(__name__)


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

    def pull(self):
        pull_image(
            image_name=self.name,
            platform=self.platform
        )


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
        dependency_steps: Dict[str, "RunnerStep"] = None,
        environment_variables: Dict[str, str] = None,
        user: str = "root",
        run_in_remote_docker_if_available: bool = False
    ):
        """
        :param name: Name of the step.
        :param script_path: Path of the shell or Python script which has to be executed by step.
        :param tracked_files_globs: List of file paths or globs to track their content while calculating cache key for
            a step.
        :param base: Another 'EnvironmentRunnerStep' or docker image that will be used as base environment where this
            step will run.
        :param dependency_steps: Collection (dict) of other steps that has to be executed in order to run this step.
            Key - Name of the env. variable that points to step's output directory with it;s result artifacts.
            Value - Step instance.
        :param environment_variables: Dist with environment variables to pass to step's script.
        :param user: Name of the user under which name run the step's script.
        :param run_in_remote_docker_if_available: If possible, run this step in the remote docker engine that
            runs inside AWS EC2 instance. It may be used, for example, to run ARM builds in the ARM-based EC2 instance,
            that is much faster than using QEMU.
        """
        self.name = name
        self.user = user
        script_path = pl.Path(script_path)
        if script_path.is_absolute():
            script_path = script_path.relative_to(SOURCE_ROOT)
        self.script_path = script_path

        tracked_files_globs = tracked_files_globs or []
        # Also add script path and shell helper script to tracked files list.
        tracked_files_globs.extend([self.script_path])

        self.tracked_files_globs = tracked_files_globs
        self._tracked_files = self._get_tracked_files(tracked_files_globs)

        self.dependency_steps = dependency_steps or {}

        # Add steps from the essentail steps collection as dependencies.
        self.dependency_steps.update(ESSENTIAL_STEPS)

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

        self.run_in_remote_docker = run_in_remote_docker_if_available

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
                for to_ignore in [
                    "__pycache__",
                    ".pytest_cache",
                ]:
                    if to_ignore in path.parent.parts:
                        skip = True
                        break

                if skip:
                    continue

                if path.name in [".DS_Store"]:
                    continue

                filtered.append(path)

            tracked_files.extend(filtered)

        return sorted(list(set(tracked_files)))

    def get_all_dependency_steps(self, recursive: bool = False) -> List['RunnerStep']:
        """
        Return dependency steps of all given steps.
        :param recursive: If True, get all dependencies recursively.
        """
        result_steps = list(self.dependency_steps.values())

        if self._base_step:
            result_steps.append(self._base_step)
            result_steps.extend(self._base_step.get_all_dependency_steps(recursive=False))

        if not recursive:
            return sort_and_filter_steps(steps=result_steps)

        nested_child_steps = []
        for step in result_steps:
            for child_step in step.get_all_dependency_steps(recursive=True):
                nested_child_steps.append(child_step)

        result_steps.extend(nested_child_steps)

        return sort_and_filter_steps(steps=result_steps)

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

    def __str__(self):
        return self.id

    def __repr__(self):
        return self.id

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

    def get_temp_output_directory(self, work_dir: pl.Path):
        output_directory = self.get_output_directory(work_dir=work_dir)
        return pl.Path(f"{output_directory}_tmp")

    def get_in_docker_temp_output_directory(self):
        return pl.Path("/tmp/step_output")

    def get_isolated_root(self, work_dir: pl.Path):
        return work_dir / "step_isolated_root" / self.id

    def get_in_docker_isolated_root(self):
        return pl.Path("/tmp/agent_source")

    def get_initial_images_dir(self, work_dir: pl.Path):
        """Get path to directory where all initial images are stored."""
        path = work_dir / "initial_images"
        if not path.exists():
            path.mkdir(parents=True)

        return path

    def get_base_image_tarball_path(self, work_dir: pl.Path):
        if self._base_step is None:
            tarball_name = self._base_docker_image.name.replace(":", "-")
            tarball_name = f"{tarball_name}-{self.architecture.as_docker_platform.value.to_dashed_str}"
            return self.get_initial_images_dir(work_dir=work_dir) / tarball_name
        else:
            return self._base_step.get_image_tarball_path(work_dir=work_dir)

    @property
    def is_step_script_is_python(self) -> bool:
        return self.script_path.suffix == ".py"

    def _get_required_steps_output_directories(
        self, work_dir: pl.Path
    ) -> Dict[str, pl.Path]:
        """
        Return path of the outputs of all steps which are required by this step.
        """
        result = {}

        for step_env_var_name, step in self.dependency_steps.items():
            result[step_env_var_name] = step.get_output_directory(work_dir=work_dir)

        return result

    def _get_required_steps_docker_output_directories(
        self, work_dir: pl.Path
    ) -> Dict[str, pl.Path]:
        """
        Return path of the docker outputs of all steps which are required by this step.
        """
        result = {}

        for step_env_var_name, step in self.dependency_steps.items():
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
            source_root_value = self.get_in_docker_isolated_root()
            step_output_path_value = self.get_in_docker_temp_output_directory()
        else:
            req_steps_env_variables = self._get_required_steps_output_directories(
                work_dir=work_dir
            )
            source_root_value = self.get_isolated_root(work_dir=work_dir)
            step_output_path_value = self.get_temp_output_directory(work_dir=work_dir)

        # Those environment variables are used by the step scripts.
        result_env_variables["SOURCE_ROOT"] = str(source_root_value)
        result_env_variables["STEP_OUTPUT_PATH"] = str(step_output_path_value)

        if self.is_step_script_is_python:
            result_env_variables["PYTHONPATH"] = source_root_value

        # Set path of the required steps as env. variables.
        for step_env_var_name, step_output_path in req_steps_env_variables.items():
            result_env_variables[step_env_var_name] = str(step_output_path)

        result_env_variables.update(self.environment_variables)

        return result_env_variables

    def _calculate_checksum(self) -> str:
        """
        The checksum of the step. It takes into account all input data that step accepts and also
            all checksums of all other steps which are used by this step.
        """

        sha256 = hashlib.sha256()

        # Add checksums of the required steps.
        for step in self.dependency_steps.values():
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

    def _run_script_locally(
        self,
        work_dir: pl.Path,
        isolated_source_root: pl.Path,
    ):
        """
        Run the step's script, whether in docker or in current system.
        :param work_dir: Path to directory where all results are stored.
        """

        env_variables_to_pass = self._get_all_environment_variables(work_dir=work_dir)

        env = os.environ.copy()
        env.update(env_variables_to_pass)

        command_args = self._get_command_args()

        check_call_with_log(command_args, env=env, cwd=str(isolated_source_root))

    def _run_script_in_docker(
            self,
            work_dir: pl.Path,
            isolated_source_root: pl.Path,
            temp_output_directory: pl.Path,
            remote_docker_host: str
    ):
        """
        Run runner step's script in docker.
        :param work_dir: Path to directory where all results are stored.
        :param remote_docker_host: If not None - host of the remote docker machine to execute script.
        """

        in_docker_isolated_source_root = self.get_in_docker_isolated_root()
        in_docker_tmp_output_directory = self.get_in_docker_temp_output_directory()

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


        remove_docker_container(
            name=self._step_container_name,
            remote_docker_host=remote_docker_host
        )

        command_args = self._get_command_args()

        # Create intermediate container
        remove_docker_container(
            name=self._step_container_name,
            remote_docker_host=remote_docker_host
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
            quiet=True
        )

        # Instead of mounting we have to copy files to an intermediate container,
        # because mounts does not work with remote docker.
        input_paths = {
            f"{isolated_source_root}/.": in_docker_isolated_source_root,
            **{f"{src}/.": dst for src, dst in required_step_mounts.items()},
            f"{temp_output_directory}/.": in_docker_tmp_output_directory,
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
            f"{in_docker_tmp_output_directory}/.": temp_output_directory,
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

    def restore_base_image_tarball_if_needed(self, work_dir: pl.Path):
        """
        Restore image tarball of the base step.
        """
        base_image_tarball = self.get_base_image_tarball_path(work_dir=work_dir)

        if base_image_tarball.exists():
            return

        if self._base_step:
            base_step = self._base_step
            base_step.restore_result_image_from_diff_if_needed(
                work_dir=work_dir,
            )
            return

        # If there's no base step, then just pull and export the base docker image.
        temp_base_image_image_tarball = pl.Path(f"{base_image_tarball}_temp")
        self._base_docker_image.pull()

        base_image_name = self._base_docker_image.name
        export_image_to_tarball(
            image_name=base_image_name,
            output_path=temp_base_image_image_tarball,
            platform=str(self.architecture.as_docker_platform.value),
        )
        temp_base_image_image_tarball.rename(base_image_tarball)
        logger.debug(
            f"Initial docker image {base_image_name} has been exported to file {base_image_tarball}"
        )

    def _get_command_args(self):
        """
        Get list with command arguments that has to be executed by step.
        """
        if self.is_step_script_is_python:
            executable = "python3"
        elif self.script_path.suffix == ".sh":
            executable = "bash"
        else:
            raise Exception(
                f"Unknown script type '{self.script_path.suffix}' for the step {self}"
            )

        return [
            executable,
            str(self.script_path),
        ]

    def is_output_result_exists(self, work_dir: pl.Path):
        """Returns True if the result of this step already exists and there's no need to run it."""
        return self.get_output_directory(work_dir=work_dir).exists()

    def run(
        self,
        work_dir: pl.Path,
        remote_docker_host_getter: Callable[["RunnerStep"], str] = None,
    ):
        """
        Run the step. Based on its initial data, it will be executed in docker or locally, on the current system.
        """

        isolated_source_root = self.get_isolated_root(work_dir)

        temp_output_directory = self.get_temp_output_directory(work_dir=work_dir)

        if temp_output_directory.exists():
            remove_root_owned_directory(path=temp_output_directory)
        temp_output_directory.mkdir(parents=True, exist_ok=True)

        output_directory = self.get_output_directory(work_dir=work_dir)
        if output_directory.exists():
            shutil.rmtree(output_directory)

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

        # Check that all required steps results exists.
        missing_steps_ids = []
        for step in self.get_all_dependency_steps():
            if not step.is_output_result_exists(work_dir=work_dir):
                missing_steps_ids.append(step.id)

        if missing_steps_ids:
            raise Exception(
                f"Can not run step '{self.id}' because not all required steps have their result outputs.\n"
                f"Required steps with missing outputs: {missing_steps_ids}"
            )

        try:
            if self.runs_in_docker:
                remote_docker_host = remote_docker_host_getter(self)

                self.restore_base_image_tarball_if_needed(work_dir=work_dir)
                if self._base_step:
                    self._base_step.import_image_tarball_if_needed(
                        work_dir=work_dir,
                        remote_docker_host=remote_docker_host
                    )

                self._run_script_in_docker(
                    work_dir=work_dir,
                    isolated_source_root=isolated_source_root,
                    temp_output_directory=temp_output_directory,
                    remote_docker_host=remote_docker_host
                )
            else:
                self._run_script_locally(
                    work_dir=work_dir,
                    isolated_source_root=isolated_source_root,
                )
        except Exception:
            files = [str(g) for g in self._tracked_files]
            logging.exception(
                f"'{self.name}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {files}."
            )
            raise

        # Remove temporary output directory to normal output directory
        chown_directory_in_docker(temp_output_directory)
        temp_output_directory.rename(output_directory)
        self.cleanup()
        logger.info(f"Step {self.name} is finished.\n")

    def cleanup(self):
        if self._step_container_name:
            remove_docker_container(
                name=self._step_container_name,
            )


class EnvironmentRunnerStep(RunnerStep):
    """
    Specialised step which performs some actions on some environment in order to prepare if for further uses.
        If this step runs in docker, it performs its actions inside specified base docker image and produces
        new image with the result environment.
        If step does not run in docker, then its actions are executed directly on current system.
    """
    def __init__(
        self,
        name: str,
        script_path: Union[pl.Path, str],
        tracked_files_globs: List[Union[str, pl.Path]] = None,
        base: Union["EnvironmentRunnerStep", DockerImageSpec] = None,
        dependency_steps: Dict[str, "RunnerStep"] = None,
        environment_variables: Dict[str, str] = None,
        user: str = "root",
        run_in_remote_docker_if_available: bool = False,
        save_result_image_as_diff: bool = True
    ):
        """

        :param name: Same as for parent RunnerStep class.
        :param script_path: Same as for parent RunnerStep class.
        :param tracked_files_globs: Same as for parent RunnerStep class.
        :param base: Same as for parent RunnerStep class.
        :param dependency_steps: Same as for parent RunnerStep class.
        :param environment_variables: Same as for parent RunnerStep class.
        :param user: Same as for parent RunnerStep class.
        :param run_in_remote_docker_if_available: Same as for parent RunnerStep class.
        :param save_result_image_as_diff: If true, the diff between image
            of the base step and result image is saved. Otherwise, the full image is saved.
        """

        super(EnvironmentRunnerStep, self).__init__(
            name=name,
            script_path=script_path,
            tracked_files_globs=tracked_files_globs,
            base=base,
            dependency_steps=dependency_steps,
            environment_variables=environment_variables,
            user=user,
            run_in_remote_docker_if_available=run_in_remote_docker_if_available
        )

        self.save_result_image_as_diff = save_result_image_as_diff

    def get_all_dependency_steps(self, recursive: bool = False) -> List['RunnerStep']:
        """
        Return dependency steps of all given steps.
        :param recursive: If True, get all dependencies recursively.
        """

        steps = super(EnvironmentRunnerStep, self).get_all_dependency_steps(recursive=recursive)

        if not recursive and self._base_step is not None:
            steps.append(self._base_step)
            steps.extend(self._base_step.get_all_dependency_steps(recursive=False))

        return sort_and_filter_steps(steps=steps)

    def get_images_dir(self, work_dir: pl.Path, temp: bool = False):
        name = self.id

        if temp:
            name = f"{name}_temp"

        return work_dir / "step_restored_images" / name

    def get_image_tarball_path(self, work_dir: pl.Path, temp: bool = False):
        if self.save_result_image_as_diff:
            return self.get_images_dir(work_dir=work_dir, temp=temp) / "image.tar"
        else:
            if temp:
                output_dir = self.get_temp_output_directory(work_dir=work_dir)
            else:
                output_dir = self.get_output_directory(work_dir=work_dir)
            return output_dir / "image.tar"

    def import_image_tarball_if_needed(self, work_dir: pl.Path, remote_docker_host: str = None):

        image_tarball = self.get_image_tarball_path(work_dir=work_dir)
        image_name = self.result_image.name

        self.restore_result_image_from_diff_if_needed(
            work_dir=work_dir
        )

        result = run_docker_command(
            ["images", "-q", image_name],
            capture_output=True,
            remote_docker_host=remote_docker_host,
        )
        output = result.stdout.decode().strip()

        if output:
            return

        if remote_docker_host:
            logger.info("    NOTE: Importing to a remote docker. It may take some time...")

        # Due to the know issue with 'docker import' - https://github.com/moby/moby/pull/43103,
        # we can not use it to import images with platform that is different from host, so
        # we have to do a workaround suggested here https://github.com/docker/cli/issues/3408#issuecomment-1023098736
        run_docker_command(
            [
                "build",
                "-t",
                image_name,
                "--platform",
                str(self.architecture.as_docker_platform.value),
                "-f",
                "-",
                "--quiet",
                str(image_tarball.parent)
            ],
            input=f"FROM scratch\nADD {image_tarball.name} /".encode(),
            remote_docker_host=remote_docker_host,
            quiet=True
        )

        # TODO: uncomment this when docker issue mentioned above is fixed (including in docker versions in CI/CD)
        # run_docker_command(
        #     [
        #         "import",
        #         "--platform",
        #         str(self.architecture.as_docker_platform.value),
        #         str(image_tarball),
        #         image_name
        #     ],
        #     remote_docker_host=remote_docker_host
        # )

        logger.info(f"Filesystem of the image of the step '{self.name}' is imported to docker.")

    def restore_result_image_from_diff_if_needed(self, work_dir: pl.Path):
        """
        Restore step's image tarball by applying diff file on a base step image tarball. Diff file
            has to be preserved from the previous step run.
        :param work_dir:
        :return:
        """

        initial_images_dir = self.get_initial_images_dir(work_dir=work_dir)
        initial_images_dir.mkdir(parents=True, exist_ok=True)

        image_tarball = self.get_image_tarball_path(work_dir=work_dir)

        base_image_tarball = self.get_base_image_tarball_path(work_dir=work_dir)

        # Return if image tarball already exists
        if image_tarball.exists():
            return

        # Make sure that base image exists.
        self.restore_base_image_tarball_if_needed(
            work_dir=work_dir
        )

        # Restore image tarball by applying diff on the base image tarball.
        temp_images_dir = self.get_images_dir(work_dir=work_dir, temp=True)
        if temp_images_dir.exists():
            shutil.rmtree(temp_images_dir)

        temp_images_dir.mkdir(parents=True)

        image_tarball = self.get_image_tarball_path(work_dir=work_dir, temp=True)

        ESSENTIAL_TOOLS_STEP.import_image_tarball_if_needed(work_dir=work_dir)

        command_args = [
            "rdiff",
            "patch",
            f"/tmp/base_image_dir/{base_image_tarball.name}",
            "/tmp/output/delta",
            f"/tmp/image_dir/{image_tarball.name}",
        ]

        step_output_dir = self.get_output_directory(work_dir=work_dir)

        subprocess.run(
            [
                "docker",
                "run",
                "-i",
                "--rm",
                "-v",
                f"{base_image_tarball.parent}:/tmp/base_image_dir",
                "-v",
                f"{step_output_dir}:/tmp/output",
                "-v",
                f"{image_tarball.parent}:/tmp/image_dir",
                ESSENTIAL_TOOLS_STEP.result_image.name,
                *command_args
            ],
            check=True
        )

        chown_directory_in_docker(temp_images_dir)
        images_dir = self.get_images_dir(work_dir=work_dir)
        temp_images_dir.rename(images_dir)
        logger.info(f"Result image for step '{self.name}' is restored from diff.")

    def _run_script_in_docker(
            self,
            work_dir: pl.Path,
            isolated_source_root: pl.Path,
            temp_output_directory: pl.Path,
            remote_docker_host: str):
        """
        For the environment step, we also have to save result image.
        """

        super(EnvironmentRunnerStep, self)._run_script_in_docker(
            work_dir=work_dir,
            isolated_source_root=isolated_source_root,
            temp_output_directory=temp_output_directory,
            remote_docker_host=remote_docker_host
        )
        temp_images_dir = self.get_images_dir(work_dir=work_dir, temp=True)

        if self.save_result_image_as_diff:

            if temp_images_dir.exists():
                shutil.rmtree(temp_images_dir)

            temp_images_dir.mkdir(parents=True)

        image_tarball = self.get_image_tarball_path(work_dir=work_dir, temp=True)

        run_docker_command(
            [
                "export",
                self._step_container_name,
                "-o",
                str(image_tarball)
            ],
            remote_docker_host=remote_docker_host
        )

        if not self.save_result_image_as_diff:
            return

        base_image_tarball = self.get_base_image_tarball_path(work_dir=work_dir)

        ESSENTIAL_TOOLS_STEP.import_image_tarball_if_needed(work_dir=work_dir)

        create_signature_command_args = [
            "rdiff",
            "signature",
            f"/tmp/base_image_dir/{base_image_tarball.name}",
            "/tmp/output/signature",
        ]

        create_delta_command_args = [
            "rdiff",
            "delta",
            "/tmp/output/signature",
            f"/tmp/image_dir/{image_tarball.name}",
            "/tmp/output/delta",
        ]

        create_signature_command = shlex.join(create_signature_command_args)

        create_delta_command = shlex.join(create_delta_command_args)

        subprocess.run(
            [
                "docker",
                "run",
                "-i",
                "--rm",
                "-v",
                f"{base_image_tarball.parent}:/tmp/base_image_dir",
                "-v",
                f"{temp_output_directory}:/tmp/output",
                "-v",
                f"{image_tarball.parent}:/tmp/image_dir",
                ESSENTIAL_TOOLS_STEP.result_image.name,
                "/bin/bash",
                "-c",
                f"{create_signature_command};{create_delta_command}"
            ],
            check=True
        )

        step_images_dir = self.get_images_dir(work_dir=work_dir)
        temp_images_dir.rename(step_images_dir)
        logger.info(f"    Diff for the image of the step '{self.name}' is created.")


@dataclasses.dataclass
class RunnerMappedPath:
    path: Union[pl.Path, str]


ALL_RUNNERS = []


class RunnerMeta(abc.ABCMeta):
    """This is a metaclass for all Runner classes.
    It's main purpose to track creation of all runner classes and tracking them in the global collection
    In order to be able to access them from CI/CD or docker.
    """

    def __init__(cls, name, bases, attrs):
        global ALL_RUNNERS

        super(RunnerMeta, cls).__init__(name, bases, attrs)

        runner_cls: Type[Runner] = cls  # NOQA

        if runner_cls.CLASS_NAME_ALIAS is not None:
            name_for_fqdn = runner_cls.CLASS_NAME_ALIAS
        else:
            name_for_fqdn = name

        module_name = attrs["__module__"]
        module = sys.modules[module_name]
        module_path = pl.Path(module.__file__).absolute()
        module_rel_path = module_path.relative_to(SOURCE_ROOT)
        module_without_ext = module_rel_path.parent / module_rel_path.stem
        module_fqdn = str(module_without_ext).replace(os.sep, ".")
        result_fqdn = f"{module_fqdn}.{name_for_fqdn}"
        runner_cls.FULLY_QUALIFIED_NAME = result_fqdn
        setattr(module, name_for_fqdn, runner_cls)

        if runner_cls.ADD_TO_GLOBAL_RUNNER_COLLECTION is True:
            ALL_RUNNERS.append(runner_cls)

    def __str__(self):
        runner_cls: Type[Runner] = self
        return runner_cls.FULLY_QUALIFIED_NAME

    def __repr__(self):
        runner_cls: Type[Runner] = self
        return runner_cls.FULLY_QUALIFIED_NAME


class Runner(metaclass=RunnerMeta):
    """
    Abstraction which combines several RunnerStep instances in order to execute them and to use their results
        in order to perform its own work.
    """

    # This class attribute is used to find and load this runner class without direct access to it.
    FULLY_QUALIFIED_NAME: str

    # If used, this alias will be used as the class name in its FULLY_QUALIFIED_NAME.
    # This may be helpful when class is created dynamically and its original name can't be used.
    CLASS_NAME_ALIAS: str = None

    # If True this class will be added to a global collection of runners
    ADD_TO_GLOBAL_RUNNER_COLLECTION: bool = False

    def __init__(self, work_dir: pl.Path = None):
        """
        :param work_dir: Path to the directory where Runner will store its results and intermediate data.
        """

        self.base_environment = type(self).get_base_environment()

        self.work_dir = pl.Path(work_dir or SOURCE_ROOT / "agent_build_output")
        output_name = type(self).FULLY_QUALIFIED_NAME.replace(".", "_")
        self.output_path = self.work_dir / "runner_outputs" / output_name

    @classmethod
    def get_base_environment(cls) -> Optional[Union[EnvironmentRunnerStep, DockerImageSpec]]:
        """
        Docker image or Environment step that is used as base environment where this runner is executed.
        """
        return None

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        """Return all steps that are required by this runner"""
        return []

    @classmethod
    def get_all_steps(cls, recursive: bool = False) -> List[RunnerStep]:
        """
        Gather all (including nested) RunnerSteps which are used by this runner.
        """

        result_steps = cls.get_all_required_steps()

        result_steps.extend(list(ESSENTIAL_STEPS.values()))

        base_environment = cls.get_base_environment()
        if base_environment:
            result_steps.append(base_environment)

        if not recursive:
            return sort_and_filter_steps(steps=result_steps)

        nested_steps = []
        for step in result_steps:
            for child_step in step.get_all_dependency_steps(recursive=True):
                nested_steps.append(child_step)

        result_steps.extend(nested_steps)

        return sort_and_filter_steps(steps=result_steps)

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
        """
        Run this Runner in docker.
        :param command_args: Command line argument for the runner.
        """
        command_args = command_args or []

        final_command_args = []

        mount_args = []

        # Mount paths that may be passed to the command line arguments.
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

        # Pass this env variable so runner knows that it runs inside docker.
        env_args = ["-e", "AGENT_BUILD_IN_DOCKER=1"]

        if isinstance(self.base_environment, EnvironmentRunnerStep):
            self.base_environment.import_image_tarball_if_needed(work_dir=self.work_dir)
            # self.base_environment.restore_result_image_from_diff_if_needed(
            #     work_dir=self.work_dir,
            # )


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
                type(self).FULLY_QUALIFIED_NAME,
                *final_command_args,
            ]
        )

        # Run chmod for the output directory of the runner, in order to fix possible permission
        # error that can be due to using root user inside the docker.
        chown_directory_in_docker(self.output_path)

    def prepare_runer(self):
        """
        Prepare runner and all its steps. This has to be done before executing runner's main functionality.
        """

        # Cleanup output if needed.
        if self.output_path.exists():
            remove_root_owned_directory(path=self.output_path)
        self.output_path.mkdir(parents=True)

        # If runner is inside the docker, then we do not need to prepare all required steps because
        # they have to be prepared before.
        # We also do the same if we are in CI/CD and all used steps results have to be restored from the cache
        if IN_CICD or IN_DOCKER:

            all_steps = self.get_all_steps()

            missing_steps = []
            for step in all_steps:
                if not step.is_output_result_exists(work_dir=self.work_dir):
                    missing_steps.append(step)

            if missing_steps:
                raise Exception(
                    f"Can not execute runner '{self.FULLY_QUALIFIED_NAME}' because some of its required steps "
                    f"don't have result directories.\nMissing steps: {missing_steps}"
                )

            return

        # Otherwise we have to find all required steps that don't have already existing results and run them.

        all_steps = self.get_all_steps(recursive=True)

        # Find steps that do not have already existing results.
        steps_with_existing_results = {}
        for step in all_steps:
            if step.is_output_result_exists(work_dir=self.work_dir):
                steps_with_existing_results[step.id] = step

        # Group steps by "stages" according to their dependencies.
        full_stages = group_steps_by_stages(steps=all_steps)

        # Remove steps that have existing results and leave only steps that do not.
        filtered_stages = remove_steps_from_stages(
            stages=full_stages,
            steps_to_remove=set(steps_with_existing_results.keys())
        )

        steps_to_run = []
        for stage in filtered_stages:
            for step_id, step in stage.items():
                steps_to_run.append(step)

        self._run_steps(
            steps=steps_to_run,
            work_dir=self.work_dir
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

            if not step.run_in_remote_docker:
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
            "--get-all-steps",
            dest="get_all_steps",
            action="store_true",
            help="Get ids of all used steps. it is meant to be used by GitHub Actions and there's no need to "
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

        if args.get_all_steps:
            steps_ids = sorted([step.id for step in cls.get_all_steps()])
            print(json.dumps(steps_ids))
            exit(0)


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


def sort_and_filter_steps(steps: List['RunnerStep']) -> List['RunnerStep']:
    """
    Get initial list of steps and create another one, but sorted by step IDs and without duplicates.
    :param steps: Steps to sort and filter.
    """
    steps_ids = {step.id: step for step in steps}

    return sorted(steps_ids.values(), key=lambda s: s.id)


def group_steps_by_stages(steps: List[RunnerStep]):
    """
    This function groups given steps into "stages" ensuring that the "dependency" steps are in the
    lower indexed stage than "dependent" steps.

    Example: There is stage 0, with the most "basic" steps, that are not dependent on anything. Then there is stage 1,
    where all steps depend on steps from the stage 0, stage 2 depends on stage 1, etc.

    By having such grouping we can guarantee that a particular step will not be executed before its "dependency" step.

    :param steps: Steps to group.
    """
    remaining_steps = {step.id: step for step in steps}
    result_stages = []

    # We go through the list of steps in multiple iterations and in each iteration has to produce its own "stage"
    while True:

        current_stage = {}

        # Each iteration we go through remaining steps and pick steps that do not have any dependencies in the same
        # remaining steps list and put it into the current stage.
        for step_id, step in remaining_steps.items():
            add = True

            for req_step in step.get_all_dependency_steps():
                if req_step.id in remaining_steps:
                    add = False
                    break

            if add:
                current_stage[step_id] = step

        # Add newly formed stage.
        result_stages.append(current_stage)

        # Remove processed steps from the remaining steps list.
        for step_id, step in current_stage.items():
            remaining_steps.pop(step_id)

        # Repeat until there are any remaining unprocessed steps
        if len(remaining_steps) == 0:
            break

    return result_stages


def remove_steps_from_stages(
    stages: List[Dict[str, RunnerStep]],
    steps_to_remove: Iterable[str],
):
    """
    Get the stages list that are produces by the `group_steps_by_stages` function and filter out steps that are
    given from the arguments.
    :param stages: Stages list to filter
    :param steps_to_remove: List of steps that has to be filtered out.
    :return: List of filtered stages.
    """
    result_stages = []

    final_steps_to_remove = set(steps_to_remove)

    for stage in stages:
        current_stage = {}
        for step_id, step in stage.items():
            if step_id not in final_steps_to_remove:
                current_stage[step_id] = step

        result_stages.append(current_stage)

    return result_stages


def run_docker_command(
    command: List,
    check: bool = True,
    capture_output: bool = False,
    input: bytes = None,
    stderr=None,
    stdout=None,
    remote_docker_host: str = None,
    quiet: bool = False
):
    """
    Run docker command.
    :param command: Command to run.
    :param remote_docker_host: Host name of the remote docker engine to execute command  within this engine.
    :param quiet: Suppress output and print it only on error.
    :param capture_output: The same as in subprocess.run.
    :param input: The same as in subprocess.run.
    :param check: The same as in subprocess.run.
    :param stdout: The same as in subprocess.run.
    :param stderr The same as in subprocess.run.
    """
    env = os.environ.copy()

    if remote_docker_host:
        env["DOCKER_HOST"] = remote_docker_host

    final_command = ["docker", *command]

    if quiet:
        stderr = subprocess.STDOUT
        stdout = subprocess.PIPE

    result = subprocess.run(
        final_command,
        env=env,
        check=False,
        input=input,
        capture_output=capture_output,
        stdout=stdout,
        stderr=stderr
    )
    if check and result.returncode != 0:

        if quiet:
            logger.error(f"Command {final_command} failed. Output:\n{result.stdout}")

        raise subprocess.CalledProcessError(
            returncode=result.returncode,
            cmd=final_command,
            output=result.stdout,
            stderr=result.stderr
        )

    return result


def pull_image(image_name: str, platform: DockerPlatformInfo):
    run_docker_command(
        ["pull", "--quiet", "--platform", str(platform), image_name],
        quiet=True
    )

def chown_directory_in_docker(path: pl.Path):
    """
    Since we produce some artifacts inside docker containers, we may face difficulties with
    manipulations of files because they may be created inside the container with the root user.
    The workaround for that is to chown result artifacts in docker again.
    """

    if IN_DOCKER:
        shutil.rmtree(path)
        return

    pull_image(
        image_name=UBUNTU_22_04,
        platform=Architecture.X86_64.as_docker_platform.value
    )

    run_docker_command(
        [
            "run",
            "-i",
            "--rm",
            "--name",
            "agent_build_step_chown",
            "-v",
            f"{path.parent}:/parent",
            UBUNTU_22_04,
            *["chown", "-R", f"{os.getuid()}:{os.getuid()}", f"/parent/{path.name}"]
        ]
    )


def remove_root_owned_directory(path: pl.Path):
    """
    Remove directory with potential permissions issue, since it may be created inside docker, which runs under root user.
    """
    to_chown = False
    try:
        shutil.rmtree(path)
    except PermissionError:
        to_chown = True
    except Exception:
        raise

    if to_chown:
        chown_directory_in_docker(path)
        shutil.rmtree(path)


def remove_docker_container(name: str, remote_docker_host: str = None):
    run_docker_command(
        [
            "rm",
            "-f",
            name
        ],
        capture_output=True,
        remote_docker_host=remote_docker_host
    )


def export_image_to_tarball(image_name: str, output_path: pl.Path, platform: str):
    """
    Export image to tarball.
    """
    container_name = image_name.replace(":", "-")
    remove_docker_container(name=container_name)
    try:
        run_docker_command(
            [
                "create",
                "--name",
                container_name,
                "--platform",
                platform,
                image_name
            ],
            quiet=True
        )

        run_docker_command(
            [
                "export", container_name, "-o", str(output_path)
            ],
        )
    finally:
        remove_docker_container(name=container_name)


def cleanup():
    if IN_DOCKER:
        return
    check_output_with_log_debug(["docker", "system", "prune", "-f", "--volumes"])
    check_output_with_log_debug(["docker", "system", "prune", "-f"])


# When a step is added to this collection, all steps that are created later will have this step as a dependency.
ESSENTIAL_STEPS = {}


# Create a special step that prepares essential tools.
# Without those tools, steps can not operate normally, for example it has tool named rdiff, which
# is needed to restore step docker images from diffs.
ESSENTIAL_TOOLS_STEP = EnvironmentRunnerStep(
    name="prepare_essential_step_tools",
    script_path=SOURCE_ROOT / "agent_build_refactored/tools/essential_runner_steps/prepare_essential_tools.sh",
    base=DockerImageSpec(
        name=UBUNTU_22_04,
        platform=Architecture.X86_64.as_docker_platform.value
    ),
    save_result_image_as_diff=False,
)

ESSENTIAL_STEPS["ESSENTIAL_TOOLS"] = ESSENTIAL_TOOLS_STEP
