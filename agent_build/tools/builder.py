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
    This abstraction performs one particular unit of work (called step) for the Builder.
    The step basically is a set of actions defined in the script file. Script file may be executed
    in docker container or directly on the current system.
    Steps are used to speed up CI/CD jobs by allowing to cache their results. Each step instance provides its
    unique id which can be used as a cache-key in the CI/CD. The id is a checksum which is calculated using information
    which is crucial for the step's result. For now, such information is:
        - script file itself.
        - other files which may be used by script.
        - environment variables (a.k.a additional settings) which are passed to a script.

    Step instance has to consistently return the same id until anything from mentioned above is changed. When that
    happens, id changes and CI/CD cache, which relied on a previous id, may be considered as invalidated.
    """
    def __init__(
        self,
        name: str,
        script_path: pl.Path,
        base_step: Union['EnvironmentBuilderStep', DockerImageSpec] = None,
        dependency_steps: List['ArtifactBuilderStep'] = None,
        additional_settings: Dict[str, str] = None,
        tracked_file_globs: List[pl.Path] = None,
    ):
        """
        :param name: name of the step.
        :param script_path: Path to the script which has to be executed during the step.
        :param base_step: If this is an instance of the 'DockerImageSpec' then the current step has to run in the
            docker container by using image, which is specified in the `base_step`.
            If this is an Instance of the `EnvironmentBuilderStep` class, then, it is used as a base
            step for the current one. That means that the current step will operate in the environment which is prepared
            by the base_step.

        :param dependency_steps: List of steps which outputs are required by the current step, so those steps
            has to be run before.
        :param additional_settings: Dictionary with string keys and values for an additional setup of the step.
        :param tracked_file_globs: List of paths/globs which has be tracked by this step in order to calculate its
            unique id. If any of specified files changes, then the id of the step also changes.
        """

        self.name = name

        self._tracked_file_globs = tracked_file_globs or []

        # List of steps which results are required for the current step.
        self._dependency_steps = dependency_steps or []

        # Collection of NAME-VALUE pairs to pass to the script.
        self._additional_settings = additional_settings or {}

        # List of paths of files which are used by this step.
        # Step calculates a checksum of those files in order to generate its unique id.
        self._tracked_file_paths = None

        self._script_path = script_path

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
                if isinstance(base_step, EnvironmentBuilderStep):
                    self.base_docker_image = base_step.result_image
                else:
                    self.base_docker_image = None

        # Directory path where this step (and maybe its nested steps) will store its result.
        # Initialized only during the run of the step.
        self._build_root: Optional[pl.Path] = None

        # The unique identifier for the step.
        self._id: Optional[str] = None

        # Paths for all files which are used by this step.
        self._tracked_file_paths: Optional[List[pl.Path]] = None

    @property
    def output_directory(self) -> pl.Path:
        return self._build_root / "step_outputs" / self.id

    @property
    def _script_output_directory(self) -> pl.Path:
        """
        A temporary directory which is used by a step's script.
        """
        return self.output_directory.parent / f"~{self.output_directory.name}"

    @property
    def tracked_file_paths(self):
        """
        Create a final list of all files that has to be included in the step's checksum calculation.
        """

        if self._tracked_file_paths:
            return self._tracked_file_paths

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
        self._tracked_file_paths = sorted(filtered_paths)
        return self._tracked_file_paths

    def _get_overall_info(self) -> Dict:
        """
        Returns dictionary with all information that is sensitive for the caching of that step.
        """
        result = {
            "name": self.name,
            # List of all files that are used by step.
            "used_files": [str(p) for p in self.tracked_file_paths],
            # Checksum of the content of that files, to catch any change in that files.
            "files_checksum": calculate_files_checksum(self.tracked_file_paths),
            # Add ids of all dependency steps. if anything significant changes in some of them, then
            # the current overall info also has to reflect that.
            "dependency_steps_ids": [s.id for s in self._dependency_steps],
            "base_step_id": self._base_step.id if self._base_step else None,
            # Add additional setting of the step.
            "additional_settings": self._additional_settings,
        }

        if self.base_docker_image:
            result["docker_image"] = self.base_docker_image.as_dict()

        return result

    @property
    def id(self) -> str:
        """
        Unique identifier of the step.
        It is based on the checksum of the step's :py:attr:`overall_info` attribute.
        Steps overall_info has to reflect any change in step's input data, so that also has to
        be reflected in its id.
        """

        if self._id:
            return self._id

        sha256 = hashlib.sha256()

        overall_info_str = json.dumps(
            self._get_overall_info(),
            sort_keys=True,
            indent=4
        )
        sha256.update(
            overall_info_str.encode()
        )

        checksum = sha256.hexdigest()

        self._id = f"{self.name}__{checksum}".lower()
        return self._id

    @property
    def all_used_steps(self):
        """
        Return list that includes all steps (including nested and the current one) that are used in that step.
        """
        result_steps = []
        # Add all dependency steps:
        for ds in self._dependency_steps:
            result_steps.extend(ds.all_used_steps)

        # Add base step if presented.
        if self._base_step:
            result_steps.extend(self._base_step.all_used_steps)

        result_steps.append(self)

        return result_steps

    @property
    def _source_root(self):
        """
        Path to a directory which contains isolated source root for the current step.
        The isolated source root is a copy of the projects source root, except the fact, that
        the isolated root contains only those files, which are tracked by the step.
        """
        return self._build_root / "step_isolated_source_roots" / self.id

    def set_build_root(self, build_root: pl.Path):

        self._build_root = build_root

        # Run all dependency steps first.
        for step in self._dependency_steps:
            step.set_build_root(build_root=self._build_root)

        # Then also run the base step.
        if self._base_step:
            self._base_step.set_build_root(build_root=self._build_root)

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

    def _prepare_working_source_root(self):
        """
        Prepare directory with source root of the project which is
        isolated directory with only files that are tracked by the step.
        """

        if self._source_root.is_dir():
            shutil.rmtree(self._source_root)

        self._source_root.mkdir(parents=True)

        # Copy all tracked files to new isolated directory.
        for file_path in self.tracked_file_paths:
            source_path = agent_build.tools.common.SOURCE_ROOT / file_path
            dest_path = self._source_root / file_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

    @property
    def runs_in_docker(self) -> bool:
        """
        Whether this step has to be performed in docker or not.
        """
        return self.base_docker_image is not None

    def _run_in_docker(
            self,
            container_name: str,
    ):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_build/tools/tools.build_in_docker'
        module,that allows to execute custom command inside docker by using 'docker build' command. It differs from
        running just in the container because we can benefit from the docker caching mechanism.
        """

        cmd_args = self._get_command_line_args()

        common.check_call_with_log([
            "docker", "rm", "-f", container_name
        ])

        in_docker_output_path = "/tmp/step/output"

        env_variables_options = []

        # Set additional settings as environment variables.
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
            f"{self._script_output_directory}:{in_docker_output_path}",
        ]

        for dependency_step in self._dependency_steps:
            in_docker_dependency_output = self._in_docker_dependency_outputs_path / dependency_step.output_directory.name
            volumes_mapping.extend([
                "-v",
                f"{dependency_step.output_directory}:{in_docker_dependency_output}"
            ])

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

    @property
    def _in_docker_dependency_outputs_path(self):
        return pl.Path("/tmp/step/dependencies")

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

        env["STEP_OUTPUT_PATH"] = str(self._script_output_directory)

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

    def run(self, build_root: pl.Path):
        """
        Run the step. Children classes should override this method.
        :param build_root: Path to a directory where to store the result of the step.
        """
        # Before start, set the specified build root
        self.set_build_root(
            build_root=build_root.absolute()
        )

        # Run all dependency steps first.
        for step in self._dependency_steps:
            step.run(build_root=self._build_root)

        # Then also run the base step.
        if self._base_step:
            self._base_step.run(build_root=self._build_root)

    def post_run(self):
        pass

    def _run(
            self
    ):
        """
        Run the script in a isolated source directory incide docker or locally.
        """

        if not self.output_directory.is_dir():

            self._prepare_working_source_root()

            try:
                if self.runs_in_docker:
                    container_name = "agent-build-builder-step"
                    self._run_in_docker(container_name)

                    common.check_call_with_log([
                        "docker", "rm", "-f", container_name
                    ])
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

        self.post_run()


class ArtifactBuilderStep(BuilderStep):
    """
    Subclass of the build step that is used to produce some build artifact for the Builder or
    another step.
    """

    def run(self, build_root: pl.Path):
        """
        Run the build step.
        :param build_root: Path to the directory where step stores all its output and results.
        """

        super(ArtifactBuilderStep, self).run(
            build_root=build_root
        )

        cache_exists = self.output_directory.is_dir()

        if not cache_exists:
            # Create a temporary directory for the output of the current step.
            if self._script_output_directory.is_dir():
                shutil.rmtree(self._script_output_directory)

            self._script_output_directory.mkdir(parents=True)

        self._run()

        if not cache_exists:

            # Rename temp output directory to a final.
            self._script_output_directory.rename(self.output_directory)


class EnvironmentBuilderStep(BuilderStep):
    """
    Subclass of the build step that is used to prepare some environment to operate for the Builder or another step
    instance.
    """
    def run(self, build_root: pl.Path):
        super(EnvironmentBuilderStep, self).run(
            build_root=build_root
        )

        cache_exists = self.output_directory.is_dir()

        # If result directory already exists and step runs in docker, then we don't have to continue because
        # result image is already in the output directory.
        if self.runs_in_docker and cache_exists:
            self.result_image.load_image()
            return

        if self._script_output_directory.is_dir():
            shutil.rmtree(self._script_output_directory)

        if cache_exists:
            self.output_directory.rename(self._script_output_directory)
        else:
            self._script_output_directory.mkdir(parents=True)

        self._run()

        self._script_output_directory.rename(self.output_directory)

    def _run_in_docker(
            self,
            container_name: str
    ):

        super(EnvironmentBuilderStep, self)._run_in_docker(
            container_name=container_name
        )

        common.check_call_with_log([
            "docker", "commit", container_name, self.result_image.name
        ])

        image_file_path = self._script_output_directory / f"{self.id}.tar"

        self.result_image.save_image(
            output_path=image_file_path
        )

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


class Builder:
    CACHEABLE_STEPS: List['BuilderStep'] = []
    NAME: str

    def __init__(self):
        self._build_root: Optional[pl.Path] = None

    def _set_build_root(self, build_root: pl.Path):
        self._build_root = build_root

        for s in type(self).CACHEABLE_STEPS:
            s.set_build_root(build_root)

    def _run_used_step(self, build_root: pl.Path):
        for cs in type(self).CACHEABLE_STEPS:
            cs.run(build_root=build_root)

    def run(self, build_root: pl.Path):
        self._set_build_root(build_root)
        self._run_used_step(build_root)
