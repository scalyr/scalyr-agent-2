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
import dataclasses
import hashlib
import json
import os
import pathlib as pl
import shutil
import logging
from typing import Union, Optional, List, Dict

import agent_build.tools.common
from agent_build.tools import common


def calculate_files_checksum(
    files: List[pl.Path]
) -> str:
    """
    Calculate and return sha256 checksum of all files from a specified list.
    """
    files = sorted(files)
    sha256 = hashlib.sha256()
    for file_path in sorted(files):
        sha256.update(str(file_path).encode())
        abs_path = agent_build.tools.common.SOURCE_ROOT / file_path
        sha256.update(abs_path.read_bytes())

    return sha256.hexdigest()


@dataclasses.dataclass
class DockerImageSpec:
    """
    Simple abstraction which encapsulates some basic information about specific docker image.
    """
    name: str
    architecture: agent_build.tools.common.Architecture

    def as_dict(self):
        return {
            "name": self.name,
            "architecture": self.architecture.value
        }

    def load_image(self):
        """
        Load docker image from tar file.
        """
        output = (
            common.check_output_with_log(
                ["docker", "images", "-q", self.name]
            ).decode().strip()
        )
        if output:
            return

        common.check_call_with_log(["docker", "load", "-i", str(self.name)])

    def save_image(self, output_path: pl.Path):
        """
        Serialize docker image into file by using 'docker save' command.
        :param output_path: Result output file.
        """
        with output_path.open("wb") as f:
            common.check_call_with_log(["docker", "save", self.name], stdout=f)


class BuilderStep:

    """
    Base abstraction that represents some action that has to be done before the Builder.
    """

    def __init__(
        self,
        name: str,
        script_path: pl.Path,
        is_environment_setup_step: bool = False,
        base_step: Union['BuilderStep', DockerImageSpec] = None,
        dependency_steps: List['BuilderStep'] = None,
        additional_settings: Dict[str, str] = None,
        cacheable: bool = False,
        tracked_file_globs: List[pl.Path] = None,
        global_steps_collection: List['BuilderStep'] = None
    ):
        """
        :param name: name of the step.
        :param script_path: Path to the script which has to be executed during the step.
        :param dependency_steps: List of steps which outputs are required by the current step, so those steps
            has to be run before.
        :param additional_settings: Dictionary with string keys and values for an additional setup of the step.
        :param cacheable: If True, Ci/CD will try to find its cache during the builder run.

        """

        self.name = name

        self._tracked_file_globs = tracked_file_globs or []

        # List of steps which results are required for the current step.
        self._dependency_steps = dependency_steps or []

        # Collection of NAME-VALUE pairs to pass to the script.
        self._additional_settings = additional_settings or {}

        self._cacheable = cacheable

        # # The root path where the step has to operate and create/locate needed files.
        # self._build_root = build_root

        # Dict with all information about a step. All things whose change may affect work of this step, has to be
        # reflected here.
        self._overall_info: Optional[Dict] = None
        # List of paths of files which are used by this step.
        # Step calculates a checksum of those files in order to generate its unique id.
        self._tracked_file_paths = None

        self._script_path = script_path

        self.is_environment_setup_step = is_environment_setup_step

        if base_step is None:
            # If there's no a base step, then this step starts from scratch on the current system.
            self._base_step = None
            self.base_docker_image = None
        else:
            if isinstance(base_step, DockerImageSpec):
                # If the base step is docker spec, then the step start from scratch too, but
                # inside docker image.
                self._base_step = None
                self.base_docker_image = base_step
            else:
                # In other case it has to be another step and the current step has to be perform on top of it.
                self._base_step = base_step

                # Also use result docker image of the base step as base docker image if presented.
                if isinstance(base_step, BuilderStep):
                    self.base_docker_image = base_step.result_image
                else:
                    self.base_docker_image = None

        # Directory path where this step (and maybe its nested steps) will store its result.
        # Initialized only during the run of the step.
        self._build_root: Optional[pl.Path] = None

        if global_steps_collection is not None and self._cacheable:
            global_steps_collection.append(self)


    @property
    def output_directory(self) -> pl.Path:
        return self._build_root / "step_outputs" / self.id

    @property
    def _temp_output_directory(self) -> pl.Path:
        return self.output_directory.parent / f"~{self.output_directory.name}"

    def _init_tracked_file_paths(self):
        """
        Create a final list of all files that has to be included in the step's checksum calculation.
        """

        found_paths = set()

        # Resolve file globs to get all files to track.
        for file_glob in self._tracked_file_globs:

            if file_glob.is_absolute():
                file_glob = file_glob.relative_to(agent_build.tools.common.SOURCE_ROOT)
            glob_paths = set(agent_build.tools.common.SOURCE_ROOT.glob(str(file_glob)))
            found_paths = found_paths.union(glob_paths)

        # To exclude all untracked files we use values from the .dockerignore file.
        dockerignore_path = agent_build.tools.common.SOURCE_ROOT / ".dockerignore"
        dockerignore_content = dockerignore_path.read_text()

        paths_excluded = []
        for line in dockerignore_content.splitlines():
            if not line:
                continue

            glob = pl.Path(line)

            # If pattern on .dockerignore  starts with '/', remove it.
            if glob.is_absolute():
                glob = glob.relative_to("/")

            # Iterate though all found paths and remove everything that matches values from .dockerignore.
            for f in found_paths:
                if not f.match(str(glob)):
                    continue

                paths_excluded.append(f)

        # Iterate through excluded paths and also exclude child paths for directories.
        for ex_path in list(paths_excluded):
            if not ex_path.is_dir():
                continue
            children_to_exclude = list(ex_path.glob("**/*"))
            paths_excluded.extend(children_to_exclude)

        # Remove excluded paths.
        filtered_paths = list(found_paths - set(paths_excluded))

        # Remove directories.
        filtered_paths = list(filter(lambda p: not p.is_dir(), filtered_paths))

        filtered_paths.append(agent_build.tools.common.SOURCE_ROOT / ".dockerignore")
        filtered_paths = [
            p.relative_to(agent_build.tools.common.SOURCE_ROOT) for p in filtered_paths
        ]

        filtered_paths.append(
            self._script_path.relative_to(agent_build.tools.common.SOURCE_ROOT)
        )
        self._tracked_file_paths = filtered_paths

    @property
    def tracked_file_paths(self):
        if not self._tracked_file_paths:
            self._init_tracked_file_paths()
            self._tracked_file_paths = sorted(self._tracked_file_paths)

        return self._tracked_file_paths

    def _init_overall_info(self):
        """
        Create overall info dictionary by collecting any information that can affect caching of that step.
        In other words, if step results has been cached by using one set of data and that data has been changed later,
        then the old cache does not reflect that changes and has to be invalidated.
        """
        self._overall_info = {
            "name": self.name,
            # List of all files that are used by step.
            "used_files": [str(p) for p in self.tracked_file_paths],
            # Checksum of the content of that files, to catch any change in that files.
            "files_checksum": calculate_files_checksum(self.tracked_file_paths),
            # Similar overall info's but from steps that are required by the current step.
            # If something changes in that dependency steps, then this step will also reflect that change.
            "dependency_steps": [s.overall_info for s in self._dependency_steps],
            # Same overall info but for the base step.
            "base_step": self._base_step.overall_info if self._base_step else None,
            # Add additional setting of the step.
            "additional_settings": self._additional_settings,
        }

        if self.base_docker_image:
            self._overall_info["docker_image"] = self.base_docker_image.as_dict()

    @property
    def overall_info(self) -> Dict:
        """
        Returns dictionary with all information that is sensitive for the caching of that step.
        """
        if not self._overall_info:
            self._init_overall_info()

        return self._overall_info

    @property
    def overall_info_str(self) -> str:
        return json.dumps(
            self.overall_info,
            sort_keys=True,
            indent=4
        )

    @property
    def id(self) -> str:
        """
        Unique identifier of the step.
        It is based on the checksum of the step's :py:attr:`overall_info` attribute.
        Steps overall_info has to reflect any change in step's input data, so that also has to
        be reflected in its id.
        """

        sha256 = hashlib.sha256()

        sha256.update(self.overall_info_str.encode())

        checksum = sha256.hexdigest()

        name = f"{self.name}__{checksum}".lower()

        return name

    @property
    def all_used_cacheable_steps(self) -> List['BuilderStep']:
        """
        Return list that includes all steps (including nested and the current one) that are used in that final step and
        are supposed to be cached in CI/CD.
        """
        result_steps = []
        # Add all dependency steps:
        for ds in self._dependency_steps:
            result_steps.extend(ds.all_used_cacheable_steps)

        # Add base step if presented.
        if self._base_step:
            result_steps.extend(self._base_step.all_used_cacheable_steps)

        # Add this step itself, but only if it cacheable.
        if self._cacheable:
            result_steps.append(self)

        return result_steps

    @property
    def all_used_cacheable_steps_ids(self) -> List[str]:
        return [s.id for s in self.all_used_cacheable_steps]

    def _check_for_cached_result(self) -> bool:
        if not self.output_directory.exists():
            return False

        # If step runs in docker, it's not a environment setup step and its result image is already
        # been found in cache, then load that existing image.
        if self.runs_in_docker and self.is_environment_setup_step:
            self.result_image.load_image()

        return True

    def set_build_root(self, build_root: pl.Path):

        self._build_root = build_root

        # Run all dependency steps first.
        for step in self._dependency_steps:
            step.set_build_root(build_root=self._build_root)

        # Then also run the base step.
        if self._base_step:
            self._base_step.set_build_root(build_root=self._build_root)

    def run(self, build_root: pl.Path):
        """
        Run the build step.
        :param build_root: Path to the directory where step stores all its output and results.
        """

        # Before start, set the specified build root
        self.set_build_root(
            build_root=build_root.absolute()
        )

        if self._check_for_cached_result():
            logging.info(
                f"The cache of the builder step {self.id} is found, reuse it and skip it."
            )
        else:

            # Run all dependency steps first.
            for step in self._dependency_steps:
                step.run(build_root=self._build_root)

            # Then also run the base step.
            if self._base_step:
                self._base_step.run(build_root=self._build_root)

            # Create a temporary directory for the output of the current step.
            if self._temp_output_directory.is_dir():
                shutil.rmtree(self._temp_output_directory)

            self._temp_output_directory.mkdir(parents=True)

            # Write step's info to a file in its output, for easier troubleshooting.
            info_file_path = self._temp_output_directory / "step_info.txt"
            info_file_path.write_text(self.overall_info_str)

            self._run()

            # Rename temp output directory to a final.
            self._temp_output_directory.rename(self.output_directory)

    @property
    def _source_root(self):
        return self._build_root / "step_isolated_source_roots" / self.id

    @property
    def result_image(self) -> Optional[DockerImageSpec]:
        """
        The name of the result docker image, just the same as cache key.
        """
        if self.runs_in_docker:
            return DockerImageSpec(
                name=self.id,
                architecture=self.base_docker_image.architecture
            )
        else:
            return None

    @property
    def runs_in_docker(self) -> bool:
        """
        Whether this step has to be performed in docker or not.
        """
        return self.base_docker_image is not None

    def _save_step_docker_container_as_image_if_needed(
            self,
            container_name: str
    ):
        """
        Save container with the result of the step execution as docker image.
        :param container_name: Name of the container to save.
        """

        # If this is not a environment setup step, then we don't need to save it's image.
        if not self.is_environment_setup_step:
            return

        common.check_call_with_log([
            "docker", "commit", container_name, self.result_image.name
        ])

        image_file_path = self._temp_output_directory / f"{self.id}.tar"

        self.result_image.save_image(
            output_path=image_file_path
        )

    @property
    def result_image_path(self):
        return self._temp_output_directory / f"{self.id}.tar"

    def _run(self):
        self._prepare_working_source_root()

        try:
            if self.runs_in_docker:
                self._run_in_docker()
            else:
                self._run_locally()
        except Exception:
            globs = [str(g) for g in self._tracked_file_globs]
            logging.error(
                f"'{type(self).__name__}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {globs}"
            )
            raise

    @property
    def _in_docker_dependency_outputs_path(self):
        return pl.Path("/tmp/step/dependencies")

    def _get_command_line_args(self) -> List[str]:
        """
        Create list with the shell command line arguments that has to execute the shell script.
            Optionally also adds cache path to the shell script as additional argument.
        :return: String with shell command that can be executed to needed shell.
        """

        required_steps_outputs = []

        for req_step in self._dependency_steps:
            if self.runs_in_docker:
                req_step_output = self._in_docker_dependency_outputs_path / req_step.output_directory.name
            else:
                req_step_output = req_step.output_directory

            required_steps_outputs.append(str(req_step_output))

        rel_script_path = self._script_path.relative_to(agent_build.tools.common.SOURCE_ROOT)

        # Determine needed shell interpreter.
        if rel_script_path.suffix == ".ps1":
            full_command_args = [
                "powershell",
            ]
        elif rel_script_path.suffix == ".sh":
            full_command_args = [
                "/bin/bash",
            ]
        elif rel_script_path.suffix == ".py":
            full_command_args = [
                "python3"
            ]

        full_command_args.extend([
            str(rel_script_path),
            *required_steps_outputs
        ])

        return full_command_args

    @property
    def _in_docker_source_root_path(self):
        return pl.Path(f"/tmp/agent_source")

    def _run_locally(self):
        """
        Run step locally by running the script on current system.
        """

        command_args = self._get_command_line_args()

        # Copy current environment.
        env = os.environ.copy()

        env["STEP_OUTPUT_PATH"] = str(self._temp_output_directory)

        # Also set all additional settings as environment variables.
        for name, value in self._additional_settings.items():
            if value is None:
                continue
            env[name] = value

        env["SOURCE_ROOT"] = str(self._source_root)


        common.check_call_with_log(
            command_args,
            env=env,
            cwd=str(self._source_root),
        )

    def _prepare_working_source_root(self):
        """
        Prepare directory with source root of the project which is
        isolated directory with only files that are tracked by the step.
        """

        if self._source_root.is_dir():
            common.check_call_with_log(f"ls -al {self._source_root}/..", shell=True)
            shutil.rmtree(self._source_root)

        self._source_root.mkdir(parents=True)

        # Copy all tracked files to new isolated directory.
        for file_path in self.tracked_file_paths:
            source_path = agent_build.tools.common.SOURCE_ROOT / file_path
            dest_path = self._source_root / file_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

    def _run_in_docker(
            self
    ):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_build/tools/tools.build_in_docker'
        module,that allows to execute custom command inside docker by using 'docker build' command. It differs from
        running just in the container because we can benefit from the docker caching mechanism.
        """

        container_name = "agent-build-builder-step"

        cmd_args = self._get_command_line_args()

        common.check_call_with_log([
            "docker", "rm", "-f", container_name
        ])

        in_docker_output_path = "/tmp/step/output"

        env_variables_options = []

        # Set additional settings ass environment variables.
        for name, value in self._additional_settings.items():
            env_variables_options.append("-e")
            env_variables_options.append(f"{name}={value}")

        env_variables_options.extend([
            "-e",
            f"STEP_OUTPUT_PATH={in_docker_output_path}",
            "-e",
            f"SOURCE_ROOT={self._in_docker_source_root_path}",
            "-e",
            "AGENT_BUILD_IN_DOCKER=1"
        ])

        if self._base_step:
            base_image = self._base_step.result_image
        else:
            base_image = self.base_docker_image

        volumes_mapping = [
            "-v",
            f"{self._source_root}:{self._in_docker_source_root_path}",
            "-v",
            f"{self._temp_output_directory}:{in_docker_output_path}",
        ]

        for dependency_step in self._dependency_steps:
            in_docker_dependency_output = self._in_docker_dependency_outputs_path / dependency_step.output_directory.name
            volumes_mapping.extend([
                "-v",
                f"{dependency_step.output_directory}:{in_docker_dependency_output}"
            ])

        try:
            common.check_call_with_log([
                "docker",
                "run",
                "-i",
                "--name",
                container_name,
                *volumes_mapping,
                "--platform",
                base_image.architecture.as_docker_platform,
                *env_variables_options,
                "--workdir",
                str(self._in_docker_source_root_path),
                base_image.name,
                *cmd_args
            ])

            self._save_step_docker_container_as_image_if_needed(
                container_name=container_name
            )
        finally:
            common.check_call_with_log([
                "docker", "rm", "-f", container_name
            ])


class Builder:

    CACHEABLE_STEPS: List['BuilderStep'] = []
    NAME: str

    def __init__(
            self,
            used_steps: List[BuilderStep] = None
    ):
        self._used_steps = used_steps or []
        self._build_root: Optional[pl.Path] = None

    @classmethod
    def all_used_cacheable_steps(cls) -> List[BuilderStep]:
        result_steps = []
        for s in cls.CACHEABLE_STEPS:
            result_steps.extend(s.all_used_cacheable_steps)

        return result_steps

    @classmethod
    def all_used_cacheable_steps_ids(cls) -> List[str]:
        return [s.id for s in cls.all_used_cacheable_steps()]

    @abc.abstractmethod
    def _run(self):
        pass

    def run(self, build_root: pl.Path):

        self._build_root = build_root

        for s in self._used_steps:
            s.run(build_root=build_root)

        self._run()

