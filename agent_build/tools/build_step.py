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
import collections
import dataclasses
import enum
import functools
import hashlib
import getpass
import json
import os
import pathlib as pl
import shlex
import re
import shutil
import stat
import subprocess
import logging
import sys
import tempfile
from typing import Union, Optional, List, Dict, Type, ClassVar

from agent_build.tools import common
from agent_build.tools import constants


_PARENT_DIR = pl.Path(__file__).parent.parent.absolute()
_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_DEPLOYMENT_STEPS_PATH = (
    _AGENT_BUILD_PATH / "tools" / "environment_deployments" / "steps"
)


_REL_AGENT_BUILD_PATH = pl.Path("agent_build")
_REL_AGENT_REQUIREMENT_FILES_PATH = _REL_AGENT_BUILD_PATH / "requirement-files"


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
        abs_path = constants.SOURCE_ROOT / file_path
        sha256.update(abs_path.read_bytes())

    return sha256.hexdigest()


class DeploymentStepError(Exception):
    """
    Special exception class for the step error.
    """


@dataclasses.dataclass
class StepCICDSettings:
    cacheable: bool = dataclasses.field(default=False)
    prebuilt_in_separate_job: bool = dataclasses.field(default=False)


class BuildStep:
    @abc.abstractmethod
    def run(self, build_root: pl.Path):
        pass

    @property
    @abc.abstractmethod
    def all_used_cacheable_steps(self) -> List['IntermediateBuildStep']:
        pass


class IntermediateBuildStep(BuildStep):

    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.
    """
    TRACKED_FILE_GLOBS = []
    NO_CI_CD_CACHE = False
    NAME: str = None
    CACHEABLE: bool = False

    def __init__(
        self,
        name: str = None,
        dependency_steps: List['IntermediateBuildStep'] = None,
        additional_settings: Dict[str, str] = None,
        ci_cd_settings: StepCICDSettings = None,
        global_steps_collection: List['BuildStep'] = None
    ):
        """
        :param deployment: The deployment instance where this step is added.
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        self.name = name or type(self).NAME

        # List of steps which results are required for the current step.
        self._dependency_steps = dependency_steps or []

        # Collection of NAME-VALUE pairs to pass to the script.
        self._additional_settings = additional_settings or {}

        # # The root path where the step has to operate and create/locate needed files.
        # self._build_root = build_root

        # Dict with all information about a step. All things whose change may affect work of this step, has to be
        # reflected here.
        self._overall_info: Optional[Dict] = None
        # List of paths of files which are used by this step.
        # Step calculates a checksum of those files in order to generate its unique id.
        self._tracked_file_paths = None
        self._base_step: Optional[BuildStep] = None

        self._ci_cd_settings = ci_cd_settings or StepCICDSettings()

        # Directory path where this step (and maybe its nested steps) will store its result.
        # Initialized only during the run of the step.
        self._build_root: Optional[pl.Path] = None

        if global_steps_collection is not None and self._ci_cd_settings.cacheable:
            global_steps_collection.append(self)


    @property
    def output_directory(self) -> pl.Path:
        return self._build_root / "step_outputs" / self.id

    @property
    def _temp_output_directory(self) -> pl.Path:
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
                file_glob = file_glob.relative_to(constants.SOURCE_ROOT)
            glob_paths = set(constants.SOURCE_ROOT.glob(str(file_glob)))
            found_paths = found_paths.union(glob_paths)

        # To exclude all untracked files we use values from the .dockerignore file.
        dockerignore_path = constants.SOURCE_ROOT / ".dockerignore"
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

        filtered_paths.append(constants.SOURCE_ROOT / ".dockerignore")
        filtered_paths = [
            p.relative_to(constants.SOURCE_ROOT) for p in filtered_paths
        ]
        self._tracked_file_paths = sorted(list(filtered_paths))
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

        # # Also reflect in the id that the step in not cacheable, so CI/CD can skip it.
        # if not self._ci_cd_settings.cacheable:
        #     name = f"{name}_skip_cache"

        return name

    @property
    def all_used_cacheable_steps(self) -> List['BuildStep']:
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
        if self._ci_cd_settings.cacheable:
            result_steps.append(self)

        return result_steps

    def _check_for_cached_result(self):
        return self.output_directory.exists()

    def run(self, build_root: pl.Path):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.
        :param additional_input: Additional input to the step as that can be passed to constructor, but since this
            input is specified after the initialization of the step, it can not be cached.
        """

        self._build_root = build_root.absolute()

        if self._check_for_cached_result():
            logging.info(
                f"The cache of the deployment step {self.id} is found, reuse it and skip it."
            )
        else:

            # Run all dependency steps first.
            for step in self._dependency_steps:
                step.run(build_root=build_root)

            # Then also run the base step.
            if self._base_step:
                self._base_step.run(build_root=build_root)

            # Create a temporary directory for the output of the current step.
            if self._temp_output_directory.is_dir():
                shutil.rmtree(self._temp_output_directory)

            self._temp_output_directory.mkdir(parents=True)

            # Write step's info to a file in its output, for easier troubleshooting.
            info_file_path = self._temp_output_directory / "step_info.txt"
            info_file_path.write_text(self.overall_info_str)

            self._run()

            if common.IN_CICD and type(self).NO_CI_CD_CACHE:
                # If we are in Ci/CD and this step is marked to not save its result in cache, then
                # put a special file in the root of the step's cache folder, so CI/CD can find this file and skip this
                # cache.
                skip_cache_file = self._temp_output_directory / "skip_cache_to_cicd"
                skip_cache_file.touch()

            # Rename temp output directory to a final.
            self._temp_output_directory.rename(self.output_directory)

    @abc.abstractmethod
    def _run(self):
        pass

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        globs = type(self).TRACKED_FILE_GLOBS[:]
        return globs


class SimpleBuildStep(IntermediateBuildStep):
    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.
    """

    def __init__(
        self,
        name: str,
        base_step: Union['IntermediateBuildStep', str] = None,
        dependency_steps: List['InstallBuildDependenciesStep'] = None,
        additional_settings: Dict[str, str] = None,
        ci_cd_settings: StepCICDSettings = None,
        global_steps_collection: List['BuildStep'] = None
    ):
        super(SimpleBuildStep, self).__init__(
            name=name,
            dependency_steps=dependency_steps,
            additional_settings=additional_settings,
            ci_cd_settings=ci_cd_settings,
            global_steps_collection=global_steps_collection
        )

        self._base_step = base_step

    @abc.abstractmethod
    def _run(self):
        pass


@dataclasses.dataclass
class DockerImageSpec:
    name: str
    architecture: constants.Architecture

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

        common.run_command(["docker", "load", "-i", str(self.name)])

    def save_image(self, output_path: pl.Path):
        """
        Serialize docker image into file by using 'docker save' command.
        :param output_path: Result output file.
        """
        with output_path.open("wb") as f:
            common.check_call_with_log(["docker", "save", self.name], stdout=f)


class ScriptBuildStep(IntermediateBuildStep):
    """
    Base abstraction that represents set of action that has to be performed in order to prepare some environment,
        for example for the build. The deployment step can be performed directly on the current machine or inside the
    docker. Results of the DeploymentStep can be cached. The caching is mostly aimed to reduce build time on the
        CI/CD such as Github Actions.
    """

    def __init__(
        self,
        name: str,
        script_path: pl.Path,
        is_dependency_step: bool,
        base_step: Union['IntermediateBuildStep', "ScriptBuildStep", DockerImageSpec] = None,
        dependency_steps: List['IntermediateBuildStep'] = None,
        additional_settings: Dict[str, str] = None,
        ci_cd_settings: StepCICDSettings = None,
        global_steps_collection: List['BuildStep'] = None
    ):
        """
        :param deployment: The deployment instance where this step is added.
        :param architecture: Architecture of the machine where step has to be performed.
        :param previous_step: If None then step is considered as first and it doesn't have to be performed on top
            of another step. If this is an instance of another DeploymentStep, then this step will be performed on top
            it. It also can be a string with some docker image. In this case the step has to be performed in that docker
            image, and the step is also considered as a first step(without previous steps).
        """

        super(ScriptBuildStep, self).__init__(
            name=name,
            dependency_steps=dependency_steps,
            additional_settings=additional_settings,
            ci_cd_settings=ci_cd_settings,
            global_steps_collection=global_steps_collection
        )

        self._script_path = script_path

        # That flag indicates that the step does not produce any artifact, instead, it
        # makes changes changes to its current environment and this environment will be the base for the
        # next step.
        self.is_dependency_step = is_dependency_step

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
                if isinstance(base_step, ScriptBuildStep):
                    self.base_docker_image = base_step.result_image
                else:
                    self.base_docker_image = None

    @property
    def _source_root(self):
        return self._build_root / "step_isolated_source_roots" / self.id

    def _init_overall_info(self):
        """
        Also add the information about docker image to the overall info.
        """
        super(ScriptBuildStep, self)._init_overall_info()
        if self.base_docker_image:
            self._overall_info["docker_image"] = self.base_docker_image.as_dict()

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

        # If this is a dependency step, then we don't need to save it's image.
        if self.is_dependency_step:
            return

        common.run_command([
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
            if self.runs_in_docker and not common.IN_DOCKER:
                self._run_in_docker()
            else:
                logging.info("555555")
                self._run_locally()
        except Exception:
            globs = [str(g) for g in self._tracked_file_globs]
            logging.error(
                f"'{type(self).__name__}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {globs}"
            )
            raise DeploymentStepError(f"Step has failed. Step name: '{self.id}'.")

    @property
    def _in_docker_dependency_outputs_path(self):
        return pl.Path("/tmp/step/dependencies")

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        globs = super(ScriptBuildStep, self)._tracked_file_globs
        globs.append(self._script_path)
        return globs

    def _get_command_line_args(self) -> List[str]:
        """
        Create list with the shell command line arguments that has to execute the shell script.
            Optionally also adds cache path to the shell script as additional argument.
        :return: String with shell command that can be executed to needed shell.
        """

        required_steps_outputs = []

        if self.runs_in_docker:
            root_dir = self._in_docker_source_root_path
        else:
            root_dir = self._source_root

        for req_step in self._dependency_steps:
            if self.runs_in_docker:
                req_step_output = self._in_docker_dependency_outputs_path / req_step.output_directory.name
            else:
                req_step_output = req_step.output_directory

            required_steps_outputs.append(str(req_step_output))

        rel_script_path = self._script_path.relative_to(constants.SOURCE_ROOT)

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

        if common.IN_CICD:
            env["IN_CICD"] = "1"


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
            source_path = constants.SOURCE_ROOT / file_path
            dest_path = self._source_root / file_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

    def _check_for_cached_result(self):
        exists = super(ScriptBuildStep, self)._check_for_cached_result()

        # If step runs in docker, it's not a dependency step and its result image is already
        # been found in cache, then load that existing image.
        if exists and self.runs_in_docker and not self.is_dependency_step:
            self.result_image.load_image()

        return exists

    def _run_in_docker(
            self
    ):
        """
        Run step in docker. It uses a special logic, which is implemented in 'agent_build/tools/tools.build_in_docker'
        module,that allows to execute custom command inside docker by using 'docker build' command. It differs from
        running just in the container because we can benefit from the docker caching mechanism.
        :param locally: If we are already in docker, this has to be set as True, to avoid loop.
        """

        container_name = "agent-build-deployment-step"

        cmd_args = self._get_command_line_args()

        common.run_command([
            "docker", "rm", "-f", container_name
        ])

        # in_docker_deployment_cache_dir = constants.DEPLOYMENT_OUTPUTS_DIR.relative_to(constants.SOURCE_ROOT)
        # in_docker_deployment_cache_dir = self._in_docker_source_root_path / in_docker_deployment_cache_dir

        #output_rel_path = self._temp_output_directory.relative_to(constants.SOURCE_ROOT)
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
            common.run_command([
                "docker", "rm", "-f", container_name
            ])


# Step that runs small script which installs requirements for the test/dev environment.
class InstallTestRequirementsDeploymentStep(ScriptBuildStep):
    @property
    def script_path(self) -> pl.Path:
        return _DEPLOYMENT_STEPS_PATH / "deploy-test-environment.sh"

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        globs = super(InstallTestRequirementsDeploymentStep, self)._tracked_file_globs
        globs.append(_REL_AGENT_REQUIREMENT_FILES_PATH / "*.txt")
        return globs


class FinalStep(BuildStep):
    def __init__(
            self,
            used_steps: List[IntermediateBuildStep]
    ):
        self._used_steps = used_steps or []

    @property
    def all_used_cacheable_steps(self) -> List[IntermediateBuildStep]:
        result_steps = []
        for s in self._used_steps:
            result_steps.extend(s.all_used_cacheable_steps)

        return result_steps

    @property
    def all_used_cacheable_steps_ids(self) -> List[str]:
        return [s.id for s in self.all_used_cacheable_steps]

    @abc.abstractmethod
    def _run(self):
        pass

    def run(self, build_root: pl.Path):
        for s in self._used_steps:
            s.run(build_root=build_root)

        self._run()

