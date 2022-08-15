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
import argparse
import dataclasses
import functools
import hashlib
import importlib.util
import json
import os
import pathlib as pl
import re
import shutil
import logging
import inspect
import sys
import time
import ast
from typing import Union, Optional, List, Dict, Type

from agent_build.tools import common
from agent_build.tools import constants
from agent_build.tools.constants import SOURCE_ROOT, DockerPlatform, DockerPlatformInfo
from agent_build.tools.common import check_call_with_log, DockerContainer, UniqueDict

log = logging.getLogger(__name__)


def remove_directory_in_docker(path: pl.Path):
    """
    Since we produce some artifacts inside docker containers, we may face difficulties with
    deleting the old ones because they may be created inside the container with the root user.
    The workaround for that to delegate that deletion to a docker container as well.
    """

    # In order to be able to remove the whole directory, we mount parent directory.
    with DockerContainer(
        name=f"agent_build_step_trash_remover",
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
        with output_path.open("wb") as f:
            common.check_call_with_log(["docker", "save", self.name], stdout=f)


@dataclasses.dataclass
class GitHubActionsSettings:
    cacheable: bool = False
    pre_build_in_separate_job: bool = False


# class RunnerStep:
#     """
#     Base abstraction that represents a shell script that has to be performed by the Runner. The step can be performed
#         directly on the current machine or inside the docker. Results of the step can be cached. The caching is mostly
#         aimed to reduce build time on the CI/CD such as GitHub Actions. In order to achieve desired caching behaviour,
#         all input data, that can affect the result, has to be taken into account.
#         For now, such data is:
#             - files which are used during steps run.
#             - environment variables which are passed to steps script.
#         All this data is used to calculate the checksum of the step and assign it as a unique id which can be used as
#             GitHub Actions cache key.
#     """
#
#
#     def __init__(
#         self,
#         name: str,
#         script_path: Union[pl.Path, str],
#         tracked_files_globs: List[Union[str, pl.Path]] = None,
#         base_step: Union["EnvironmentRunnerStep", DockerImageSpec] = None,
#         required_steps: Dict[str, "ArtifactRunnerStep"] = None,
#         environment_variables: Dict[str, str] = None,
#         github_actions_settings: "RunnerStep.GitHubActionsSettings" = None,
#     ):
#         """
#         :param name: Name of the step.
#         :param script_path: Path to a script which has to be executed by the step.
#         :param tracked_files_globs: List of file path or globs which has to be tracked by the step during checksum
#             calculation.
#         :param base_step: Represents environment in which the current step has to be performed.
#             If step is instance of EnvironmentRunnerStep, then it will be performed on top of step (if base step runs
#                 in docker, then this step will run in base step's result image).
#             If step is DockerImageSpec, then this step will run inside the image which is specified in spec.
#             If None, runs on current system.
#         :param required_steps: Dict of steps which outputs are required by this step.
#             Values of that dict are instances of required steps, keys - names of the environment variables by which,
#             the current step can access outputs of required steps.
#         :param  environment_variables:
#             Name-to-value strings dictionary with environment variables that has to be passed to step.
#                 NOTE: Names and values of env. variables are included into the checksum calculation
#         :param cacheable: Boolean flag that indicates that this step has to be cached inGitHub Actions.
#         :param pre_build_in_cicd: Boolean flag that indicated that this step can be pre-built in GitHub Actions in a
#             separate job.
#         """
#         self.name = name
#         script_path = pl.Path(script_path)
#         if script_path.is_absolute():
#             script_path = script_path.relative_to(SOURCE_ROOT)
#
#         self.script_path = script_path
#
#         self._tracked_files_globs = tracked_files_globs or []
#
#         if self.script_path.suffix == ".py":
#             self._tracked_files_globs.extend(self._get_python_script_dependencies())
#
#         # Also add script path and shell helper script to tracked files list.
#         self._tracked_files_globs.extend(
#             [
#                 self.script_path,
#                 "agent_build/tools/steps_libs/step_runner.sh",
#             ]
#         )
#         self._tracked_files = self._get_tracked_files()
#         self.base_step: Optional[EnvironmentRunnerStep] = None
#
#         if isinstance(base_step, RunnerStep):
#             # The previous step is specified.
#             # The base docker image is a result image of the previous step.
#             self.base_docker_image = base_step.result_image
#             self.initial_docker_image = base_step.initial_docker_image
#             self.base_step = base_step
#         elif isinstance(base_step, DockerImageSpec):
#             # The previous step isn't specified, but it is just a docker image.
#             self.base_docker_image = base_step
#             self.initial_docker_image = base_step
#             self.base_step = None
#         else:
#             # the previous step is not specified.
#             self.base_docker_image = None
#             self.initial_docker_image = None
#             self.base_step = None
#
#         self.runs_in_docker = bool(self.initial_docker_image)
#
#         self.environment_variables = environment_variables or {}
#
#         self.required_steps = required_steps or {}
#
#         if self.runs_in_docker:
#             self._step_container_name = f"{self.result_image.name}-container".replace(
#                 ":", "-"
#             )
#         else:
#             self._step_container_name = None
#
#         self.github_actions_settings = (
#             github_actions_settings or RunnerStep.GitHubActionsSettings()
#         )
#
#     def _get_python_script_dependencies(self):
#         """
#         This method recursively searches for all imports that a step's python script does, and makes sure that all
#         imported packages/modules are from a special "allowed" 'agent_build/tools/steps_libs' packages. This allowed
#         packages are just pieces of code that are somehow used in those steps
#
#
#         :return:
#         """
#
#         allowed_package = "agent_build.tools.steps_libs"
#
#         def scan_module_imports(module_filename):
#
#             imported_modules = set()
#             dependency_modules_filenames = set()
#
#             def visit_import(node):
#                 for name in node.names:
#                     imported_modules.add(name.name)
#
#             def visit_import_from(node):
#                 # if node.module is missing it's a "from . import ..." statement
#                 # if level > 0 it's a "from .submodule import ..." statement
#                 if node.module is not None and node.level == 0:
#                     imported_modules.add(node.module)
#
#                     for name in node.names:
#                         full_name = f"{node.module}.{name.name}"
#                         try:
#                             importlib.import_module(full_name)
#                         except ImportError:
#                             continue
#
#                         imported_modules.add(full_name)
#                 else:
#                     raise Exception(
#                         f"Relative import at line '{node.lineno}' in module '{module_filename}'. "
#                         f"Relative imports are not allowed in mudules which are inside the '{allowed_package}' "
#                         f"package. Without this limitation step caching is not possible."
#                     )
#
#             node_iter = ast.NodeVisitor()
#             node_iter.visit_Import = visit_import
#             node_iter.visit_ImportFrom = visit_import_from
#
#             dependency_modules_filenames.add(module_filename)
#
#             node_iter.visit(ast.parse(module_filename.read_text()))
#
#             for imported_module_name in imported_modules:
#                 if not imported_module_name.startswith("agent_build"):
#                     continue
#
#                 if not imported_module_name.startswith(allowed_package):
#                     raise Exception(
#                         f"Python module '{module_filename}' imports module '{imported_module_name}' which is outside of "
#                         f"allowed package '{allowed_package}'. Importing modules "
#                         f"outside of allowed package will make step caching impossible."
#                     )
#
#                 imported_module = sys.modules[imported_module_name]
#                 module_filename = pl.Path(imported_module.__file__)
#                 dependency_modules_filenames.update(scan_module_imports(module_filename))
#
#             return dependency_modules_filenames
#         #
#         # script_path_parts = script_path.parts
#         # parent_module_name = ".".join(script_path_parts[:-1])
#         # script_module_name = f"{parent_module_name}.{script_path.stem}"
#
#         return list(scan_module_imports(self.script_path))
#
#     def _get_tracked_files(self) -> List[pl.Path]:
#         """
#         Resolve steps tracked files globs into final list of files.
#         """
#         self._tracked_file_globs = [pl.Path(g) for g in self._tracked_files_globs]
#         # All final file paths to track.
#         tracked_files = []
#
#         # Resolve file globs to get all files to track.
#         for file_glob in set(self._tracked_file_globs):
#             file_glob = pl.Path(file_glob)
#
#             if file_glob.is_absolute():
#                 if not str(file_glob).startswith(str(SOURCE_ROOT)):
#                     raise ValueError(
#                         f"Tracked file glob {file_glob} is not part of the source {SOURCE_ROOT}"
#                     )
#
#                 file_glob = file_glob.relative_to(SOURCE_ROOT)
#
#             found = list(constants.SOURCE_ROOT.glob(str(file_glob)))
#
#             tracked_files.extend(found)
#
#         return sorted(list(set(tracked_files)))
#
#     def get_all_cacheable_steps(self) -> List["RunnerStep"]:
#         """
#         Get list of all steps (including nested) which are used by this step.
#         """
#         result = []
#
#         # Include current step itself, if needed.
#         if self.github_actions_settings.cacheable:
#             result.append(self)
#
#         for step in self.required_steps.values():
#             result.extend(step.get_all_cacheable_steps())
#
#         if self.base_step:
#             result.extend(self.base_step.get_all_cacheable_steps())
#
#         return result
#
#     @property
#     def id(self) -> str:
#         """
#         Unique (suppose to be) identifier of the step.
#         Its format - "<step_name>-<docker_image_name>-<docker-image-platform>-<step-checksum>".
#         If step does not run in docker, then docker related part are excluded.
#         """
#         result = f"{self.name}"
#         if self.runs_in_docker:
#             image_name = self.initial_docker_image.name.replace(":", "-")
#             image_platform = self.initial_docker_image.platform.replace("/", "-")
#             result = f"{result}-{image_name}-{image_platform}"
#         result = f"{result}-{self.checksum}"
#         return result
#
#     @property
#     def result_image(self) -> Optional[DockerImageSpec]:
#         """
#         The spec of the result docker image.
#         """
#         if not self.runs_in_docker:
#             return None
#
#         return DockerImageSpec(
#             # Image name just the same as id.
#             name=self.id,
#             platform=self.base_docker_image.platform,
#         )
#
#     def get_output_directory(self, work_dir: pl.Path):
#         return
#
#     def _get_required_steps_output_directories(
#             self,
#             output_directory: pl.Path
#     ) -> Dict[str, pl.Path]:
#         """
#         Return path of the outputs of all steps which are required by this step.
#         """
#         result = {}
#
#         for step_env_var_name, step in self.required_steps.items():
#             if self.runs_in_docker:
#                 step_dir = pl.Path("/tmp/required_steps") / step.output_directory.name
#             else:
#                 step_dir = output_directory
#
#             result[step_env_var_name] = step_dir
#
#         return result
#
#     def _get_all_environment_variables(
#             self,
#             output_directory: pl.Path
#     ):
#         """Gather and return all environment variables that has to be passed to step's script."""
#         result_env_variables = UniqueDict()
#
#         # Set path of the required steps as env. variables.
#         for (
#             step_env_var_name,
#             step_output_path,
#         ) in self._get_required_steps_output_directories(
#             output_directory=output_directory
#         ).items():
#             result_env_variables[step_env_var_name] = str(step_output_path)
#
#         result_env_variables.update(self.environment_variables)
#
#         if common.IN_CICD:
#             result_env_variables["IN_CICD"] = "1"
#
#         return result_env_variables
#
#     @property
#     def checksum(self) -> str:
#         """
#         The checksum of the step. It takes into account all input data that step accepts and also
#             all checksums of all other steps which are used by this step.
#         """
#
#         sha256 = hashlib.sha256()
#
#         # Add checksums of the required steps.
#         for step in self.required_steps.values():
#             sha256.update(step.checksum.encode())
#
#         # Add base step's checksum.
#         if self.base_step:
#             sha256.update(self.base_step.checksum.encode())
#
#         # Add checksums of environment variables.
#         for name, value in self._get_all_environment_variables().items():
#             sha256.update(name.encode())
#             sha256.update(value.encode())
#
#         # Calculate the sha256 for each file's content, filename.
#         for file_path in self._tracked_files:
#             sha256.update(str(file_path.relative_to(constants.SOURCE_ROOT)).encode())
#             sha256.update(file_path.read_bytes())
#
#         return sha256.hexdigest()
#
#     @staticmethod
#     def _remove_output_directory(
#             output_directory: pl.Path
#     ):
#         if output_directory.is_dir():
#             remove_directory_in_docker(output_directory)
#         elif output_directory.is_symlink():
#             output_directory.unlink()
#
#     def _restore_cache(
#             self,
#             output_directory: pl.Path,
#             cache_directory: pl.Path
#     ) -> bool:
#         """
#         Searches for cached results, if found, then they are reused and the run is skipped.
#         :return: Boolean that indicates that the cache is found and step can be skipped.
#         """
#         pass
#
#     def _save_to_cache(
#         self,
#         is_skipped: bool,
#         output_directory: pl.Path,
#         cache_directory: pl.Path
#     ):
#         """
#         Saved results of the finished step to cache, if needed.
#         :param is_skipped: Boolean flag that indicates that the main run method has been skipped.
#         """
#         pass
#
#     def _pre_run(self) -> bool:
#         """Function that runs after the step main run function."""
#         pass
#
#     def _post_run(self):
#         """
#         Function that runs after the step main run function.
#         """
#         pass
#
#     def _run_script(
#         self,
#         output_directory: pl.Path,
#         cache_directory: pl.Path,
#         isolated_source_root: pl.Path
#     ):
#         """
#         Run the step's script, whether in docker or in current system.
#         """
#
#         if self.runs_in_docker:
#             #final_isolated_source_root = pl.Path("/tmp/agent_source")
#             final_cache_path = "/tmp/step_cache"
#             final_output_path = "/tmp/step_output"
#         else:
#             #final_isolated_source_root = isolated_source_root
#             final_cache_path = cache_directory
#             final_output_path = output_directory
#
#         if self.script_path.suffix == ".py":
#             script_type = "python"
#         else:
#             script_type = "shell"
#
#         command_args = [
#             "env",
#             "bash",
#             # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
#             # and also provides some helper functions such as caching.
#             "agent_build/tools/steps_libs/step_runner.sh",
#             str(self.script_path),
#             str(final_cache_path),
#             str(final_output_path),
#             script_type,
#         ]
#
#         # Run step directly on the current system
#         if not self.runs_in_docker:
#             env = os.environ.copy()
#
#             python_path = env["PYTHONPATH"]
#             for p in python_path.split(os.pathsep):
#                 p = pl.Path(p)
#                 if not str(p).startswith(str(SOURCE_ROOT)):
#                     continue
#                 new_p = isolated_source_root / p.relative_to(SOURCE_ROOT)
#                 python_path = python_path.replace(str(p), str(new_p))
#
#             python_path = f"{python_path}{os.pathsep}{isolated_source_root}"
#             env["PYTHONPATH"] = python_path
#
#             env.update(self._get_all_environment_variables())
#             common.check_call_with_log(
#                 command_args, env=env, cwd=str(isolated_source_root)
#             )
#             return
#
#         # Run step in docker.
#         common.check_call_with_log(["docker", "rm", "-f", self._step_container_name])
#
#         mount_options = []
#         for (
#             step_env_var_name,
#             step_output_path,
#         ) in self._get_required_steps_output_directories().items():
#             step = self.required_steps[step_env_var_name]
#             mount_options.extend(["-v", f"{output_directory}:{step_output_path}"])
#
#         docker_container_source_root = pl.Path("/tmp/agent_source")
#         # Mount isolated source root, output path and cache to be able to use them later.
#         mount_options.extend(
#             [
#                 "-v",
#                 f"{isolated_source_root}:{docker_container_source_root}",
#                 "-v",
#                 f"{cache_directory}:{final_output_path}",
#                 "-v",
#                 f"{output_directory}:{final_cache_path}",
#             ]
#         )
#
#         env_options = []
#         for env_var_name, env_var_val in self._get_all_environment_variables().items():
#             env_options.extend(["-e", f"{env_var_name}={env_var_val}"])
#
#         common.check_call_with_log(
#             [
#                 "docker",
#                 "run",
#                 "-i",
#                 "--name",
#                 self._step_container_name,
#                 "--workdir",
#                 str(docker_container_source_root),
#                 *mount_options,
#                 *env_options,
#                 self.base_docker_image,
#                 *command_args,
#             ]
#         )
#
#     def run(self, work_dir: pl.Path):
#         """
#         Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.
#         """
#
#         output_directory = work_dir / "step_output" / self.id
#         cache_directory = work_dir / "step_cache" / self.id
#         isolated_source_root = work_dir / "step_isolated_root" / self.id
#
#         output_directory.parent.mkdir(parents=True, exist_ok=True)
#         skipped = self._restore_cache(
#             output_directory=output_directory,
#             cache_directory=cache_directory
#         )
#         if not skipped:
#             logging.info(f"Run step {self.name}.")
#             for step in self.required_steps.values():
#                 step.run(work_dir=work_dir)
#
#             if self.base_step:
#                 self.base_step.run(work_dir=work_dir)
#
#             self._remove_output_directory(
#                 output_directory=output_directory
#             )
#             output_directory.mkdir(parents=True, exist_ok=True)
#
#             # Create directory to store only tracked files.
#             if isolated_source_root.exists():
#                 shutil.rmtree(isolated_source_root)
#             isolated_source_root.mkdir(parents=True)
#
#             # Copy all tracked files into a new isolated directory.
#             for file_path in self._tracked_files:
#                 dest_path = isolated_source_root / file_path.parent.relative_to(
#                     constants.SOURCE_ROOT
#                 )
#                 dest_path.mkdir(parents=True, exist_ok=True)
#                 shutil.copy2(file_path, dest_path)
#
#             # # Create __init__.py files for all parent packages of the "steps_libs" package,
#             # # so it can be imported from isolated source.
#             # dir_path = self._isolated_source_root / "agent_build/tools/steps_libs"
#             # while dir_path != self._isolated_source_root:
#             #     init_path = dir_path / "__init__.py"
#             #     init_path.touch()
#             #     dir_path = dir_path.parent
#
#             env_variables_str = "\n    ".join(
#                 f"{n}='{v}'" for n, v in self._get_all_environment_variables().items()
#             )
#             logging.info(
#                 f"Start step: {self.id}\n"
#                 f"Passed env. variables:\n    {env_variables_str}\n"
#             )
#             try:
#                 self._run_script(
#                     output_directory=output_directory,
#                     cache_directory=cache_directory,
#                     isolated_source_root=isolated_source_root
#                 )
#             except Exception:
#                 globs = [str(g) for g in self._tracked_file_globs]
#                 logging.exception(
#                     f"'{type(self).__name__}' has failed. "
#                     "HINT: Make sure that you have specified all files. "
#                     f"For now, tracked files are: {globs}."
#                 )
#                 raise
#             finally:
#                 self.cleanup()
#         else:
#             log.info(f"Result if the step '{self.id}' is found in cache, skip.")
#
#         self._save_to_cache(
#             is_skipped=skipped,
#             output_directory=output_directory,
#             cache_directory=cache_directory
#         )
#
#     def cleanup(self):
#         if self._step_container_name:
#             check_call_with_log(["docker", "rm", "-f", self._step_container_name])


# @dataclasses.dataclass
# class RunnerStepPaths:
#     work_dir: pl.Path
#     step_id: str
#     output_directory: pl.Path = dataclasses.field(init=False)
#     cache_directory: pl.Path = dataclasses.field(init=False)
#     isolated_root: pl.Path = dataclasses.field(init=False)
#
#     def __post_init__(self):
#         object.__setattr__(
#             self, "output_directory", self.work_dir / "step_output" / self.step_id
#         )
#         object.__setattr__(
#             self, "cache_directory", self.work_dir / "step_cache" / self.step_id
#         )
#         object.__setattr__(
#             self, "isolated_root", self.work_dir / "step_isolated_root" / self.step_id
#         )


class RunnerStep:
    """
    Base abstraction that represents a shell script that has to be performed by the Runner. The step can be performed
        directly on the current machine or inside the docker. Results of the step can be cached. The caching is mostly
        aimed to reduce build time on the CI/CD such as GitHub Actions. In order to achieve desired caching behaviour,
        all input data, that can affect the result, has to be taken into account.
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
                "agent_build/tools/steps_libs/step_runner.sh",
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

        if not github_actions_settings:
            self.github_actions_settings = GitHubActionsSettings()

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

            found = list(constants.SOURCE_ROOT.glob(str(file_glob)))

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

        if common.IN_CICD:
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
            sha256.update(str(file_path.relative_to(constants.SOURCE_ROOT)).encode())
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

        if self.runs_in_docker:
            final_isolated_source_root = pl.Path("/tmp/agent_source")
            final_cache_path = "/tmp/step_cache"
            final_output_path = "/tmp/step_output"
        else:
            final_isolated_source_root = self.get_isolated_root(work_dir=work_dir)
            final_cache_path = self.get_cache_directory(work_dir=work_dir)
            final_output_path = self.get_output_directory(work_dir=work_dir)

        isolated_source_root = self.get_isolated_root(work_dir=work_dir)
        cache_directory = self.get_cache_directory(work_dir=work_dir)
        output_directory = self.get_output_directory(work_dir=work_dir)

        if self.script_path.suffix == ".py":
            script_type = "python"
        else:
            script_type = "shell"

        command_args = [
            "env",
            "bash",
            # For the bash scripts, there is a special 'step_runner.sh' bash file that runs the given shell script
            # and also provides some helper functions such as caching.
            "agent_build/tools/steps_libs/step_runner.sh",
            str(self.script_path),
            str(final_cache_path),
            str(final_output_path),
            script_type,
        ]

        env_variables_to_pass = self._get_all_environment_variables(work_dir=work_dir)

        # Run step directly on the current system
        if not self.runs_in_docker:
            env = os.environ.copy()

            python_path = env["PYTHONPATH"]
            for p in python_path.split(os.pathsep):
                p = pl.Path(p)
                if not str(p).startswith(str(SOURCE_ROOT)):
                    continue
                new_p = isolated_source_root / p.relative_to(SOURCE_ROOT)
                python_path = python_path.replace(str(p), str(new_p))

            python_path = f"{python_path}{os.pathsep}{isolated_source_root}"
            env["PYTHONPATH"] = python_path

            env.update(env_variables_to_pass)
            common.check_call_with_log(
                command_args, env=env, cwd=str(isolated_source_root)
            )
            return

        docker_isolated_source_root = pl.Path("/tmp/agent_source")
        docker_cache_directory = "/tmp/step_cache"
        docker_output_directory = "/tmp/step_output"

        # Run step in docker.
        common.check_call_with_log(["docker", "rm", "-f", self._step_container_name])

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
                f"{isolated_source_root}:{docker_isolated_source_root}",
                "-v",
                f"{cache_directory}:{docker_cache_directory}",
                "-v",
                f"{output_directory}:{docker_output_directory}",
            ]
        )

        env_options = []
        for env_var_name, env_var_val in env_variables_to_pass.items():
            env_options.extend(["-e", f"{env_var_name}={env_var_val}"])

        common.check_call_with_log(
            [
                "docker",
                "run",
                "-i",
                "--name",
                self._step_container_name,
                "--workdir",
                str(docker_isolated_source_root),
                *mount_options,
                *env_options,
                self._base_docker_image.name,
                *command_args,
            ]
        )
        a = 10

    def run(self, work_dir: pl.Path):
        """
        Run the step. Based on its initial data, it will be performed in docker or locally, on the current system.
        """

        output_directory = self.get_output_directory(work_dir)
        cache_directory = self.get_cache_directory(work_dir)
        isolated_source_root = self.get_isolated_root(work_dir)

        output_directory.parent.mkdir(parents=True, exist_ok=True)
        skipped = self._restore_cache(
            output_directory=output_directory, cache_directory=cache_directory
        )
        if not skipped:
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
                dest_path = isolated_source_root / file_path.parent.relative_to(
                    constants.SOURCE_ROOT
                )
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
                globs = [str(g) for g in self.tracked_files_globs]
                logging.exception(
                    f"'{type(self).__name__}' has failed. "
                    "HINT: Make sure that you have specified all files. "
                    f"For now, tracked files are: {globs}."
                )
                raise
            finally:
                self.cleanup()
        else:
            log.info(f"Result if the step '{self.id}' is found in cache, skip.")

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
        If step does not run in docker, then its actions are performed directly on current system.
    """

    def _restore_cache(
        self, output_directory: pl.Path, cache_directory: pl.Path
    ) -> bool:
        if self.runs_in_docker:
            # Before the run, check if there is already an image with the same name. The name contains the checksum
            # of all files which are used in it, so the name identity also guarantees the content identity.
            output = (
                common.check_output_with_log(
                    ["docker", "images", "-q", self.result_image.name]
                )
                .decode()
                .strip()
            )

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
        # Save results in cache.
        if self.runs_in_docker and not is_skipped:
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

    It also allows to run itself through command line, by generating command line argument from the signature
        of its constructor. This feature, for example, is used by Runner to run itself in docker.
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

    # def __new__(cls, *args, **kwargs):
    #     """
    #     Before creating new instance of the runner, analyze its signature, and save input values that are passed to the
    #         constructor. We need to save constructor's arguments in order to run the same Runner with the same arguments
    #         in docker.
    #     """
    #     obj = super(Runner, cls).__new__(cls)
    #
    #     # Get signature of the constructor and save arguments according to that signature.
    #     init_signature = inspect.signature(obj.__init__)
    #     input_values = {}
    #     pos_arg_count = 0
    #     for name, param in init_signature.parameters.items():
    #         if param.kind.POSITIONAL_ONLY:
    #             value = args[pos_arg_count]
    #             pos_arg_count += 1
    #         else:
    #             value = kwargs.get(name, param.default)
    #
    #         input_values[name] = value
    #
    #     # Set gathered input values as new runner's attribute, so it can use them later.
    #     obj.input_values = input_values
    #     return obj

    @staticmethod
    def runer_cli_command(f, run: bool = True):
        @functools.wraps
        def wrapper(self, *args, **kwargs):
            # Get signature of the function and save arguments according to its signature.
            input_values = {}
            pos_arg_count = 0
            for name, param in inspect.signature(f).parameters.items():
                if param.kind.POSITIONAL_ONLY:
                    value = args[pos_arg_count]
                    pos_arg_count += 1
                else:
                    value = kwargs.get(name, param.default)

                input_values[name] = value

            # Set gathered input values as new runner's attribute, so it can use them later.
            self._input_values = input_values

            if run:
                self.run()
            return f(self, *args, **kwargs)

        setattr(wrapper, "is_cli_command", True)
        setattr(wrapper, "original", f)

        return wrapper

    def __init__(
        self,
        work_dir: pl.Path,
        # required_runners: List["Runner"] = None,
        required_steps: List[RunnerStep] = None,
        # base_environment: Union[RunnerStep, str] = None,
    ):
        """
        :param required_runners: Instantiated version of runner classes that are specified in REQUIRED_RUNNERS_CLASSES
            class attribute.
        :param required_steps: Final list of RunnerSteps to be executed by this runner. If not specified, then just
            the `REQUIRED_STEPS` class attribute is used.
        :param base_environment: if specified, overrides the `BASE_ENVIRONMENT` class attribute.
        """

        self.base_environment = type(self).BASE_ENVIRONMENT
        self.required_steps = required_steps or type(self).REQUIRED_STEPS[:]
        self.required_runners = {}

        self.work_dir = work_dir
        output_name = type(self).get_fully_qualified_name().replace(".", "_")
        self.output_path = work_dir / "runner_outputs" / output_name

        self._input_values = {}

    # def _append_required_steps(self, required_steps: List[RunnerStep]):
    #     self.required_steps.extend(required_steps)

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        pass

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
            module_name_parts = (
                str(pl.Path(module.__file__).relative_to(SOURCE_ROOT))
                .strip(".py")
                .split(os.sep)
            )
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
        if not common.IN_DOCKER:
            if self.base_environment:
                self.base_environment.run(work_dir=self.work_dir)

            for required_step in self.required_steps:
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
            "/scalyr-agent-2/agent_build/scripts/runner_helper.py",
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

        if common.IN_CICD:
            env_options.extend(["-e", "IN_CICD=1"])

        # Finally execute runner with generated command line arguments in container.
        common.check_call_with_log(
            [
                "docker",
                "run",
                "-i",
                "--rm",
                "-v",
                f"{constants.SOURCE_ROOT}:/scalyr-agent-2",
                *additional_mounts,
                *env_options,
                docker_image.name,
                *command_args,
            ]
        )

    def _run(self):
        """
        Function where Runners main work is performed.
        """
        pass

    # @classmethod
    # def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
    #     """
    #     Create argparse parser with all arguments which are generated from constructor's signature.
    #     """
    #
    #     parser.add_argument(
    #         "--get-all-cacheable-steps",
    #         dest="get_all_cacheable_steps",
    #         action="store_true",
    #         help="Get ids of all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
    #         "use it manually.",
    #     )
    #
    #     parser.add_argument(
    #         "--run-all-cacheable-steps",
    #         dest="run_all_cacheable_steps",
    #         action="store_true",
    #         help="Run all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
    #         "use it manually.",
    #     )
    #
    #     if cls.__init__ is Runner.__init__:
    #         # Do this only if constructor was overridden in child classes.
    #         return
    #
    #     runner_signature = inspect.signature(cls.__init__)
    #     argument_docs = {}
    #     arg_name = None
    #     # Parse argument docstring to put them as 'help' for parser arguments.
    #     if cls.__init__.__doc__:
    #         for line in cls.__init__.__doc__.splitlines():
    #             m = re.match(r"\s*:param ([a-zA-Z_]+):\s*(.*)", line.strip())
    #             if m:
    #                 arg_name = m.group(1)
    #                 text = m.group(2)
    #                 argument_docs[arg_name] = text.strip()
    #             elif arg_name:
    #                 argument_docs[arg_name] += line.strip()
    #
    #     for name, param in runner_signature.parameters.items():
    #         arg_name = name.replace("_", "-")
    #
    #         if name == "self":
    #             continue
    #
    #         additional_args = {}
    #         if param.annotation is bool:
    #             additional_args["action"] = "store_true"
    #
    #         if "action" not in additional_args:
    #             if param.annotation in [List, list] or str(param.annotation).startswith(
    #                 "typing.List"
    #             ):
    #                 arg_type = str
    #             else:
    #                 arg_type = param.annotation
    #             additional_args["type"] = arg_type
    #
    #         parser.add_argument(
    #             f"--{arg_name}",
    #             dest=name,
    #             default=param.default,
    #             required=param.kind == inspect.Parameter.POSITIONAL_ONLY,
    #             help=argument_docs.get(name),
    #             **additional_args,
    #         )

    @classmethod
    def _get_command_line_functions(cls):
        result = {}
        for m_name, value in inspect.getmembers(cls):
            if hasattr(value, "is_cli_command"):
                result[m_name] = value

        return result

    # @classmethod
    # def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
    #     """
    #     Create argparse parser with all arguments which are generated from constructor's signature.
    #     """
    #
    #     parser.add_argument(
    #         "--get-all-cacheable-steps",
    #         dest="get_all_cacheable_steps",
    #         action="store_true",
    #         help="Get ids of all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
    #         "use it manually.",
    #     )
    #
    #     parser.add_argument(
    #         "--run-all-cacheable-steps",
    #         dest="run_all_cacheable_steps",
    #         action="store_true",
    #         help="Run all used cacheable steps. it is meant to be used by GitHub Actions and there's no need to "
    #         "use it manually.",
    #     )
    #
    #     parser.add_argument(
    #         "--work-dir",
    #         dest="work_dir",
    #         default=str(SOURCE_ROOT / "agent_build_output"),
    #         help="Directory path where all final and intermediate results are store, maybe helpful during debugging."
    #     )
    #
    #     subparsers = parser.add_subparsers(dest="command", required=True)
    #
    #     for m_name, value in cls._get_command_line_functions().items():
    #         original_func = getattr(value, "original")
    #
    #         docstring = inspect.getdoc(original_func)
    #         docstring = "".join(docstring.split(os.linesep))
    #         # Make docstring's ':param' statements begin with new line.
    #         docstring = re.sub(r"(:\s*param\s+[^:]+\s*:)", r"\n\1", docstring)
    #         general_doc, params_string = docstring.split("\n", 1)
    #         subparser = subparsers.add_parser(
    #             m_name,
    #             help=general_doc,
    #         )
    #
    #         param_matches = re.findall(
    #             r":\s*param\s+([^:]+)\s*:(.*)",
    #             params_string,
    #         )
    #
    #         argument_docs = {name: text.strip() for name, text in param_matches}
    #
    #         signature = inspect.signature(original_func)
    #         for p_name, param in signature.parameters.items():
    #             arg_name = p_name.replace("_", "-")
    #
    #             if p_name == "self":
    #                 continue
    #
    #             additional_args = {}
    #             if param.annotation is bool:
    #                 additional_args["action"] = "store_true"
    #
    #             if "action" not in additional_args:
    #                 if param.annotation in [List, list] or str(
    #                     param.annotation
    #                 ).startswith("typing.List"):
    #                     arg_type = str
    #                 else:
    #                     arg_type = param.annotation
    #                 additional_args["type"] = arg_type
    #
    #             subparser.add_argument(
    #                 f"--{arg_name}",
    #                 dest=p_name,
    #                 required=param.kind == inspect.Parameter.POSITIONAL_ONLY,
    #                 help=argument_docs.get(p_name),
    #                 **additional_args,
    #             )

    #     # @classmethod
    #     # def handle_command_line_arguments(
    #     #     cls,
    #     #     args,
    #     # ):
    #     #     """
    #     #     Handle parsed command line arguments and perform needed actions.
    #     #     """
    #     #     if args.get_all_cacheable_steps:
    #     #         steps = cls.get_all_cacheable_steps()
    #     #         steps_ids = [step.id for step in steps]
    #     #         print(json.dumps(steps_ids))
    #     #         exit(0)
    #     #
    #     #     if args.run_all_cacheable_steps:
    #     #         steps = cls.get_all_cacheable_steps()
    #     #         for step in steps:
    #     #             step.run()
    #     #         exit(0)
    #     #
    #     #     # Collect constructor's arguments from command line arguments by
    #     #     # checking the constructor's signature.
    #     #     if cls.__init__ is not Runner.__init__:
    #     #         # Do this only if constructor was overridden in child classes.
    #     #         cls_signature = inspect.signature(cls.__init__)
    #     #         constructor_args = {}
    #     #         for name, param in cls_signature.parameters.items():
    #     #             if name == "self":
    #     #                 continue
    #     #
    #     #             value = getattr(args, name, None)
    #     #
    #     #             if value:
    #     #                 if param.annotation in [List, list] or str(
    #     #                     param.annotation
    #     #                 ).startswith("typing.List"):
    #     #                     # this is comma separated string
    #     #                     value = value.split(",")
    #     #
    #     #             constructor_args[name] = value
    #     #     else:
    #     #         constructor_args = {}
    #     #
    #     #     runner = cls(**constructor_args)
    #     #
    #     #     runner.run()

    # @classmethod
    # def handle_command_line_arguments(
    #     cls,
    #     args,
    # ):
    #     """
    #     Handle parsed command line arguments and perform needed actions.
    #     """
    #     if args.get_all_cacheable_steps:
    #         steps = cls.get_all_cacheable_steps()
    #         steps_ids = [step.id for step in steps]
    #         print(json.dumps(steps_ids))
    #         exit(0)
    #
    #     work_dir = pl.Path(args.work_dir)
    #
    #     if args.run_all_cacheable_steps:
    #         steps = cls.get_all_cacheable_steps()
    #         for step in steps:
    #             step.run(work_dir=work_dir)
    #         exit(0)
    #
    #     cmd_func = cls._get_command_line_functions()[args.command]
    #     original_func = getattr(cmd_func, "original")
    #
    #     # Do this only if constructor was overridden in child classes.
    #     signature = inspect.signature(original_func)
    #     pos_args = []
    #     kw_args = {}
    #     for p_name, param in signature.parameters.items():
    #         if p_name == "self":
    #             continue
    #
    #         value = getattr(args, p_name, None)
    #
    #         if value:
    #             if param.annotation in [List, list] or str(param.annotation).startswith(
    #                 "typing.List"
    #             ):
    #                 # this is comma separated string
    #                 value = value.split(",")
    #
    #         if param.kind == inspect.Parameter.POSITIONAL_ONLY:
    #             if value is not None:
    #                 pos_args.append(value)
    #         else:
    #             kw_args[p_name] = value
    #
    #     runner = cls()
    #     original_func(runner, *pos_args, **kw_args)

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
