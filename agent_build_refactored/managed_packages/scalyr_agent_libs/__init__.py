import abc
import argparse
import shutil
import pathlib as pl
import hashlib
from typing import List, Union, Dict, Type


from agent_build_refactored.tools.steps_libs.utils import calculate_files_checksum
from agent_build_refactored.tools.steps_libs.subprocess_with_log import check_call_with_log
from agent_build_refactored.tools.constants import IN_DOCKER, SOURCE_ROOT, AGENT_SUBDIR_NAME, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT, Architecture
from agent_build_refactored.tools.runner import Runner, EnvironmentRunnerStep, ArtifactRunnerStep, DockerImageSpec, GitHubActionsSettings, RunnerStep, RunnerMappedPath

from agent_build_refactored.managed_packages.scalyr_agent_python3 import BUILD_PYTHON_STEPS, PREPARE_TOOLSET_STEPS


# name of the dependency package with agent requirement libraries.
AGENT_LIBS_PACKAGE_NAME = "scalyr-agent-libs"
AGENT_LIBS_WHEELS_PACKAGE_NAME = "scalyr-agent-libs-wheels"


def create_build_wheels_step(
        name: str,
        prepare_wheels_base_image: Union[EnvironmentRunnerStep, DockerImageSpec],
):
    return ArtifactRunnerStep(
        name=name,
        script_path="agent_build_refactored/managed_packages/scalyr_agent_libs/system_python/build_steps/build_wheels.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/scalyr_agent_libs/system_python/build_steps/pysnmp_setup.patch"
        ],
        base=prepare_wheels_base_image,
        environment_variables={
            "SUBDIR_NAME": AGENT_SUBDIR_NAME,
            "REQUIREMENTS": REQUIREMENTS_COMMON
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


BUILD_SYSTEM_PYTHON_AGENT_PACKAGES_ROOTS = ArtifactRunnerStep(
    name="build_system_python_agent_libs_packages_roots",
    script_path="agent_build_refactored/managed_packages/scalyr_agent_libs/system_python/build_steps/build_packages_roots.sh",
    tracked_files_globs=[
        "agent_build_refactored/managed_packages/scalyr_agent_libs/system_python/files/scalyr-agent-python3",
        "agent_build_refactored/managed_packages/scalyr_agent_libs/files/config/config.ini",
        "agent_build_refactored/managed_packages/scalyr_agent_libs/files/scalyr-agent-2-libs.py",
        "agent_build_refactored/managed_packages/scalyr_agent_libs/files/config/additional-requirements.txt",
    ],
    base=PREPARE_TOOLSET_STEPS[Architecture.X86_64],
    required_steps={
        "PREPARE_WHEELS_PY36": create_build_wheels_step(
            name="build_wheels_py36",
            prepare_wheels_base_image=DockerImageSpec(
                name="python:3.6",
                platform=Architecture.X86_64.as_docker_platform.value
            )
        ),
        "PREPARE_WHEELS": create_build_wheels_step(
            name="build_wheels",
            prepare_wheels_base_image=PREPARE_TOOLSET_STEPS[Architecture.X86_64],
        ),
    },
    environment_variables={
        "SUBDIR_NAME": AGENT_SUBDIR_NAME,
        "REQUIREMENTS": REQUIREMENTS_COMMON,
        "PLATFORM_DEPENDENT_REQUIREMENTS": REQUIREMENTS_COMMON_PLATFORM_DEPENDENT,
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)


# class PackagesBuilder(Runner, metaclass=abc.ABCMeta):
#     PACKAGE_TYPE: str
#
#     @abc.abstractmethod
#     def build(self, stable_versions_file: str = None):
#         pass
#
#     @classmethod
#     def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
#         super(PackagesBuilder, cls).add_command_line_arguments(parser)
#
#         parser.add_argument("build")
#
#         parser.add_argument(
#             "--stable_versions-file",
#             required=False
#         )
#
#     @classmethod
#     def handle_command_line_arguments(
#             cls,
#             args,
#     ):
#         super(PackagesBuilder, cls).handle_command_line_arguments(args=args)
#
#         work_dir = pl.Path(args.work_dir)
#
#         builder = cls(work_dir=work_dir)
#
#         builder.build(
#             stable_versions_file=args.stable_versions_file
#         )
#         if not IN_DOCKER:
#             output_path = SOURCE_ROOT / "build"
#             if output_path.exists():
#                 shutil.rmtree(output_path)
#             shutil.copytree(
#                 builder.output_path,
#                 output_path,
#                 dirs_exist_ok=True,
#             )
#
#
# class SystemPythonAgentLibsBuilder(PackagesBuilder):
#     PACKAGE_ARCHITECTURES: List[str]
#
#     @classmethod
#     def get_base_environment(cls):
#         return PREPARE_TOOLSET_STEPS[Architecture.X86_64]
#
#     @classmethod
#     def get_all_required_steps(cls) -> List[RunnerStep]:
#         steps = super(SystemPythonAgentLibsBuilder, cls).get_all_required_steps()
#         steps.extend([
#             BUILD_SYSTEM_PYTHON_AGENT_PACKAGES_ROOTS,
#         ])
#         return steps
#
#     @classmethod
#     def get_package_checksum(cls):
#         sha256 = hashlib.sha256()
#
#         for package_arch in cls.PACKAGE_ARCHITECTURES:
#             sha256.update(package_arch.encode())
#
#         sha256.update(BUILD_SYSTEM_PYTHON_AGENT_PACKAGES_ROOTS.checksum.encode())
#
#         # Add arguments that are used to build package.
#         for arg in cls._get_package_build_cmd_args():
#             sha256.update(arg.encode())
#
#         # Also calculate checksum of install scriptlets to reflect possible changes in them.
#         scriptlets_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/scalyr_agent_libs/install_scriptlets"
#         scriptlets = [
#             scriptlets_path / "system-python-preinstall.sh",
#             scriptlets_path / "system-python-postinstall.sh",
#             scriptlets_path / "preuninstall.sh",
#         ]
#         sha256 = calculate_files_checksum(
#             files_paths=scriptlets,
#             sha256=sha256
#         )
#         return sha256.hexdigest()
#
#     @classmethod
#     def _get_agent_libs_wheels_package_build_cmd_args(cls) -> List[str]:
#         """
#         Returns list of arguments for command that build agent-libs package.
#         """
#
#         description = "Dependency package which provides Python requirement libraries which are used by the agent " \
#                       "from the 'scalyr-agent-2 package'"
#
#         return [
#             # fmt: off
#             "fpm",
#             "-s", "dir",
#             "-a", "all",
#             "-t", cls.PACKAGE_TYPE,
#             "-n", AGENT_LIBS_WHEELS_PACKAGE_NAME,
#             "--license", '"Apache 2.0"',
#             "--vendor", "Scalyr",
#             "--provides", "scalyr-agent-2",
#             "--description", description,
#             "--depends", "bash >= 3.2",
#             "--directories", f"/usr/share/{AGENT_SUBDIR_NAME}/agent-libs",
#             "--url", "https://www.scalyr.com",
#             "--deb-user", "root",
#             "--deb-group", "root",
#             "--rpm-user", "root",
#             "--rpm-group", "root",
#             # fmt: on
#         ]
#
#     @classmethod
#     def _get_package_build_cmd_args(cls) -> List[str]:
#         """
#         Returns list of arguments for command that build agent-libs package.
#         """
#
#         scriptlets_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/scalyr_agent_libs/install_scriptlets"
#
#         description = "Dependency package which provides Python requirement libraries which are used by the agent " \
#                       "from the 'scalyr-agent-2 package'"
#
#         return [
#             # fmt: off
#             "fpm",
#             "-s", "dir",
#             "-t", cls.PACKAGE_TYPE,
#             "-n", AGENT_LIBS_PACKAGE_NAME,
#             "--license", '"Apache 2.0"',
#             "--vendor", "Scalyr",
#             "--provides", "scalyr-agent-2",
#             "--description", description,
#             "--depends", "bash >= 3.2",
#             "--url", "https://www.scalyr.com",
#             "--before-install", str(scriptlets_path / "system-python-preinstall.sh"),
#             "--after-install", str(scriptlets_path / "system-python-postinstall.sh"),
#             "--before-remove", str(scriptlets_path / "preuninstall.sh"),
#             "--directories", f"/usr/lib/{AGENT_SUBDIR_NAME}/agent-libs",
#             "--directories", f"/var/lib/{AGENT_SUBDIR_NAME}",
#             "--directories", f"/etc/{AGENT_SUBDIR_NAME}",
#             "--deb-user", "root",
#             "--deb-group", "root",
#             "--rpm-user", "root",
#             "--rpm-group", "root",
#             # fmt: on
#         ]
#
#     def build(self, stable_versions_file: str = None):
#         self.run_required()
#
#         if self.runs_in_docker:
#             args = ["build"]
#             if stable_versions_file:
#                 args.extend([
#                     "--stable-versions-file", RunnerMappedPath(stable_versions_file)
#                 ])
#             self.run_in_docker(
#                 command_args=args
#             )
#             return
#
#         version = _get_dependency_package_version_to_use(
#             checksum=SYSTEM_PYTHON_AGENT_LIBS_BUILDERS_CHECKSUM,
#             package_name=AGENT_LIBS_PACKAGE_NAME,
#             stable_versions_file_path=stable_versions_file
#         )
#
#         package_roots = self.output_path / "package_roots"
#         agent_libs_min_package_root = package_roots / "agent_libs_min_package_root"
#         step_output = BUILD_SYSTEM_PYTHON_AGENT_PACKAGES_ROOTS.get_output_directory(work_dir=self.work_dir)
#         shutil.copytree(
#              step_output / "agent-libs-wheels",
#             agent_libs_min_package_root,
#         )
#
#         check_call_with_log(
#             [
#                 *self._get_agent_libs_wheels_package_build_cmd_args(),
#                 "-v", version,
#                 "-C", str(agent_libs_min_package_root),
#                 "--verbose"
#             ],
#             cwd=str(self.output_path)
#         )
#
#         agent_libs_package_root = package_roots / "agent_libs_package_root"
#         shutil.copytree(
#             step_output / "agent-libs",
#             agent_libs_package_root,
#         )
#
#         for package_arch in self.PACKAGE_ARCHITECTURES:
#             check_call_with_log(
#                 [
#                     *self._get_package_build_cmd_args(),
#                     "-a", package_arch,
#                     "-v", version,
#                     "-C", str(agent_libs_package_root),
#                     "--depends", f"{AGENT_LIBS_WHEELS_PACKAGE_NAME} >= {version}",
#                     "--verbose"
#                 ],
#                 cwd=str(self.output_path)
#             )
#
#
# class DebAgentSystemPythonDependenciesBuilder(SystemPythonAgentLibsBuilder):
#     PACKAGE_ARCHITECTURES = [
#         "amd64",
#         "armhf",
#         "armel",
#         "ppc64el",
#         "s390x",
#         "mips64el",
#         "riscv64",
#         "i386",
#     ]
#     PACKAGE_TYPE = "deb"
#
#
# class RpmAgentSystemPythonDependenciesBuilder(SystemPythonAgentLibsBuilder):
#     PACKAGE_ARCHITECTURES = [
#         "aarch64",
#         "x86_64",
#         "ppc64le",
#         "s390x",
#         "i386"
#     ]
#     PACKAGE_TYPE = "rpm"
#
#
# SYSTEM_PYTHON_AGENT_LIBS_BUILDERS: Dict[str, Union[Type[SystemPythonAgentLibsBuilder]]] = {
#     "deb-system-python": DebAgentSystemPythonDependenciesBuilder,
#     "rpm-system-python": RpmAgentSystemPythonDependenciesBuilder,
# }
#
#
# def _calculate_all_agent_libs_packages_checksum():
#     sha256 = hashlib.sha256()
#     for builder_name in sorted(SYSTEM_PYTHON_AGENT_LIBS_BUILDERS.keys()):
#         builder_cls = SYSTEM_PYTHON_AGENT_LIBS_BUILDERS[builder_name]
#         sha256.update(builder_cls.get_package_checksum().encode())
#
#     return sha256.hexdigest()
#
#
# SYSTEM_PYTHON_AGENT_LIBS_BUILDERS_CHECKSUM = _calculate_all_agent_libs_packages_checksum()