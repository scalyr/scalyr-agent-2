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
import hashlib
import json
import logging
import operator
import shutil
import subprocess
import argparse
import os
import pathlib as pl
import re
import sys
import tempfile
from typing import List, Tuple, Optional, Dict, Type, Union


from agent_build_refactored.tools.steps_libs.utils import calculate_files_checksum
from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep, RunnerMappedPath, EnvironmentRunnerStep, DockerImageSpec,GitHubActionsSettings, IN_DOCKER
from agent_build_refactored.tools.constants import SOURCE_ROOT, DockerPlatform, Architecture, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_fhs_agent_files, add_config
from agent_build_refactored.tools.constants import AGENT_PYTHON_PACKAGE_NAME, AGENT_WHEELS_PACKAGE_NAME, AGENT_SUBDIR_NAME, AGENT_REQUIREMENTS_PACKAGE_NAME, AGENT_PACKAGE_NAME
from agent_build_refactored.managed_packages.scalyr_agent_python3 import PREPARE_TOOLSET_STEPS, BUILD_EMBEDDED_PYTHON_STEPS, CREATE_AGENT_PYTHON3_SYSTEM_PACKAGE_ROOT_STEP, CREATE_AGENT_PYTHON3_EMBEDDED_PACKAGE_ROOT_STEPS
from agent_build_refactored.managed_packages.scalyr_agent_wheels import CREATE_AGENT_WHEELS_EMBEDDED_PYTHON_PACKAGE_ROOT_STEPS, CREATE_AGENT_WHEELS_SYSTEM_PYTHON_PACKAGE_ROOT_STEP

logger = logging.getLogger(__name__)

"""
This module is responsible for building Python agent for Linux distributions with package managers.

It defines builder class that is responsible for the building of the Linux agent deb and rpm packages that are 
    managed by package managers such as apt and yum.

Besides building the agent package itself, it also builds dependency packages:
    - scalyr-agent-python3
    - scalyr-agent-libs

These packages are needed to make agent package completely independent of a target system.


The 'scalyr-agent-python3' package provides Python interpreter that is specially built to be used by the agent.
    Its main feature that it is built against the oldest possible version of gLibc, so it has to be enough to maintain
    only one build of the package in order to support all target systems.


The 'scalyr-agent-libs' package provides requirement libraries for the agent, for example Python 'requests' or
    'orjson' libraries. It is intended to ship it separately from the 'scalyr-agent-python3' because we update
    agent's requirements much more often than Python interpreter.

The structure of the mentioned packages has to guarantee that files of these packages does not interfere with
    files of local system Python interpreter. To achieve that, the dependency packages files are installed in their
    own 'sub-directories'

    For now there are two subdirectories:
        - /usr/lib/scalyr-agent-2/python3 - for Python3 interpreter package.
        - /usr/lib/scalyr-agent-2/agent-libs - for agent requirement libraries.

    and agent from the 'scalyr-agent-2' package has to use the
    '/usr/lib/scalyr-agent-2/bin/python3' executable.
"""

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
# class RpmAgentSystemPythonDependenciesBuilder(AgentSystemPythonDependenciesBuilder):
#     PACKAGE_ARCHITECTURES = [
#         "aarch64",
#         "x86_64",
#         "ppc64le",
#         "s390x",
#         "i386"
#     ]


OTHER_PACKAGES_ARCHITECTURES = {
    "deb": [
        "armhf",
        "armel",
        "ppc64el",
        "s390x",
        "mips64el",
        "riscv64",
        "i386",
    ],
    "rpm": [
        "ppc64le",
        "s390x",
        "i386"
    ],
}

_FPM_COMMON_BUILD_ARGS = [
    # fmt: off
    "-s", "dir",
    "--license", '"Apache 2.0"',
    "--vendor", "Scalyr",
    "--provides", "scalyr-agent-2",
    "--depends", "bash >= 3.2",
    "--url", "https://www.scalyr.com",
    "--deb-user", "root",
    "--deb-group", "root",
    "--rpm-user", "root",
    "--rpm-group", "root",
    # fmt: on
]


class BuilderBase(Runner):

    @abc.abstractmethod
    def build(self, stable_versions_file: str = None):
        pass


    @property
    def result_packages_path(self) -> pl.Path:
        return self.output_path / "packages"

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(BuilderBase, cls).add_command_line_arguments(parser)

        subparsers = parser.add_subparsers(dest="command")
        build_parser = subparsers.add_parser("build")

        build_parser.add_argument(
            "--stable_versions-file",
            required=False
        )

    @classmethod
    def handle_command_line_arguments(
            cls,
            args,
    ):
        super(BuilderBase, cls).handle_command_line_arguments(args=args)

        if args.command == "build":
            work_dir = pl.Path(args.work_dir)
            builder = cls(work_dir=work_dir)

            builder.build(
                stable_versions_file=args.stable_versions_file
            )
            if not IN_DOCKER:
                output_path = SOURCE_ROOT / "build"
                if output_path.exists():
                    shutil.rmtree(output_path)
                shutil.copytree(
                    builder.result_packages_path,
                    output_path,
                    dirs_exist_ok=True,
                )
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            exit(1)



class ManagedPackagesBuilder(BuilderBase):
    """
    Builder class that is responsible for the building of the Linux agent deb and rpm packages that are managed by package
        managers such as apt and yum.
    """

    # type of the package, aka 'deb' or 'rpm'
    PACKAGE_TYPE: str

    EMBEDDED_PYTHON_ARCHITECTURE: Architecture = None


    # package architecture, for example: amd64 for deb.
    DEPENDENCY_PACKAGES_ARCHITECTURE: Architecture

    # Instance of the step that builds filesystem for the python package.
    PYTHON_BUILD_STEP: ArtifactRunnerStep
    # Instance of the step that builds filesystem for the agent-libs package.
    AGENT_REQUIREMENTS_BUILD_STEP: ArtifactRunnerStep

    # Name of a target distribution in the packagecloud.
    PACKAGECLOUD_DISTRO: str

    # Version of a target distribution in the packagecloud.
    PACKAGECLOUD_DISTRO_VERSION: str

    @classmethod
    def get_base_environment(cls):
        if cls.EMBEDDED_PYTHON_ARCHITECTURE:
            return PREPARE_TOOLSET_STEPS[cls.EMBEDDED_PYTHON_ARCHITECTURE]
        else:
            return PREPARE_TOOLSET_STEPS[Architecture.X86_64]

    @classmethod
    def has_embedded_python(cls):
        return cls.EMBEDDED_PYTHON_ARCHITECTURE is not None

    @classmethod
    def get_build_python_package_root_step(cls) -> ArtifactRunnerStep:
        if cls.EMBEDDED_PYTHON_ARCHITECTURE is not None:
            return CREATE_AGENT_PYTHON3_EMBEDDED_PACKAGE_ROOT_STEPS[cls.EMBEDDED_PYTHON_ARCHITECTURE]
        else:
            return CREATE_AGENT_PYTHON3_SYSTEM_PACKAGE_ROOT_STEP

    @classmethod
    def get_create_agent_requirements_package_root_step(cls) -> ArtifactRunnerStep:
        if cls.EMBEDDED_PYTHON_ARCHITECTURE is not None:
            return CREATE_AGENT_WHEELS_EMBEDDED_PYTHON_PACKAGE_ROOT_STEPS[cls.EMBEDDED_PYTHON_ARCHITECTURE]
        else:
            return CREATE_AGENT_WHEELS_SYSTEM_PYTHON_PACKAGE_ROOT_STEP

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(ManagedPackagesBuilder, cls).get_all_required_steps()

        steps.extend([
            cls.get_build_python_package_root_step(),
            cls.get_create_agent_requirements_package_root_step(),
        ])
        return steps

    @property
    def packages_output_path(self) -> pl.Path:
        """
        Directory path with result packages.
        """
        return self.output_path / "packages"

    @staticmethod
    def _parse_package_version_parts(version: str) -> Tuple[int, str]:
        """
        Deconstructs package version string and return tuple with version's iteration and checksum parts.
        """
        iteration, checksum = version.split("+")
        return int(iteration), checksum

    def _parser_package_file_parts(self, package_file_name: str):
        if self.PACKAGE_TYPE == "deb":
            # split filename to name and extension
            filename, ext = package_file_name.split(".")
            # then split name to name prefix, version and architecture.
            package_name, version, arch = filename.split("_")
        else:
            # split filename to name, arch, and extension
            filename, arch, ext = package_file_name.split(".")
            # split with release
            prefix, release = filename.rsplit("-", 1)
            # split with version
            package_name, version = prefix.rsplit("-", 1)

        return package_name, version, arch, ext

    @classmethod
    def get_python_package_name(cls) -> str:
        if cls.EMBEDDED_PYTHON_ARCHITECTURE:
            return f"{AGENT_PYTHON_PACKAGE_NAME}-embedded"
        else:
            return f"{AGENT_PYTHON_PACKAGE_NAME}-system"

    @classmethod
    def get_agent_wheels_package_name(cls) -> str:
        if cls.EMBEDDED_PYTHON_ARCHITECTURE:
            return f"{AGENT_WHEELS_PACKAGE_NAME}-embedded"
        else:
            return f"{AGENT_WHEELS_PACKAGE_NAME}-system"

    @classmethod
    def get_python_package_build_args(cls) -> List[str]:
        """
        Returns list of arguments for the command that builds python package.
        """

        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        if cls.EMBEDDED_PYTHON_ARCHITECTURE:
            architecture = cls.EMBEDDED_PYTHON_ARCHITECTURE
        else:
            architecture = Architecture.UNKNOWN

        package_architecture = architecture.get_as_package_arch(package_type=cls.PACKAGE_TYPE)

        return [
            # fmt: off
            "fpm",
            "-a", package_architecture,
            "-t", cls.PACKAGE_TYPE,
            "-n", cls.get_python_package_name(),
            *_FPM_COMMON_BUILD_ARGS,
            # fmt: on
            ]

    @classmethod
    def get_agent_wheels_package_build_args(cls) -> List[str]:
        """
        Returns list of arguments for the command that builds python package.
        """

        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        if cls.EMBEDDED_PYTHON_ARCHITECTURE:
            architecture = cls.EMBEDDED_PYTHON_ARCHITECTURE
        else:
            architecture = Architecture.UNKNOWN

        package_architecture = architecture.get_as_package_arch(package_type=cls.PACKAGE_TYPE)

        return [
            # fmt: off
            "fpm",
            "-a", package_architecture,
            "-t", cls.PACKAGE_TYPE,
            "-n", cls.get_agent_wheels_package_name(),
            *_FPM_COMMON_BUILD_ARGS
            # fmt: on
            ]

    @classmethod
    def get_python_package_checksum(cls) -> str:
        sha256 = hashlib.sha256()
        # Add checksum of the step that builds package files.
        sha256.update(
            cls.get_build_python_package_root_step().checksum.encode()
        )
        # Add arguments that are used to build package.
        for arg in cls.get_python_package_build_args():
            sha256.update(arg.encode())

        return sha256.hexdigest()

    @classmethod
    def get_agent_wheels_package_checksum(cls) -> str:
        sha256 = hashlib.sha256()

        # Also add checksum of python packages.
        sha256.update(_ALL_PYTHON_PACKAGES_CHECKSUM.encode())

        # Add checksum of the step that builds package files.
        sha256.update(
            cls.get_create_agent_requirements_package_root_step().checksum.encode()
        )
        # Add arguments that are used to build package.
        for arg in cls.get_agent_wheels_package_build_args():
            sha256.update(arg.encode())

        return sha256.hexdigest()

    def build_python_package(self, stable_versions_file: str = None):
        version, should_build = _get_dependency_package_version_to_use(
            checksum=_ALL_PYTHON_PACKAGES_CHECKSUM,
            package_name=AGENT_PYTHON_PACKAGE_NAME,
            stable_versions_file_path=stable_versions_file
        )

        if not should_build:
            return version

        package_root = self.get_build_python_package_root_step().get_output_directory(work_dir=self.work_dir) / "root"

        self.packages_output_path.mkdir(exist_ok=True)
        check_call_with_log(
            [
                *self.get_python_package_build_args(),
                "-v", version,
                "-C", str(package_root),
                "--verbose"
            ],
            cwd=str(self.packages_output_path)
        )

        return version

    def build_agent_wheels_package(
            self,
            python_package_version: str,
            stable_versions_file: str = None
    ):
        version, should_build = _get_dependency_package_version_to_use(
            checksum=_ALL_AGENT_WHEELS_PACKAGES_CHECKSUM,
            package_name=AGENT_WHEELS_PACKAGE_NAME,
            stable_versions_file_path=stable_versions_file
        )

        if not should_build:
            return version

        output = self.get_create_agent_requirements_package_root_step().get_output_directory(work_dir=self.work_dir)
        package_root = output / "root"
        package_scriptlets = output / "scriptlets"

        self.result_packages_path.mkdir(exist_ok=True)
        check_call_with_log(
            [
                *self.get_agent_wheels_package_build_args(),
                "--depends", f"{self.get_python_package_name()} = {python_package_version}",
                "--after-install", str(package_scriptlets / "system-python-postinstall.sh"),
                "-v", version,
                "-C", str(package_root),
                "--verbose"
            ],
            cwd=str(self.result_packages_path)
        )

        return version

    def build(self, stable_versions_file: str = None):
        self.run_required()

        if self.runs_in_docker:
            args = ["build"]
            if stable_versions_file:
                args.extend([
                    "--stable-versions-file", RunnerMappedPath(stable_versions_file)
                ])
            self.run_in_docker(
                command_args=args
            )
            return

        version, should_build = _get_dependency_package_version_to_use(
            checksum=_ALL_AGENT_WHEELS_PACKAGES_CHECKSUM,
            package_name=AGENT_WHEELS_PACKAGE_NAME,
            stable_versions_file_path=stable_versions_file
        )

        if not should_build:
            return version

        python_package_version = self.build_python_package(stable_versions_file=stable_versions_file)

        agent_wheels_package_version = self.build_agent_wheels_package(
            python_package_version=python_package_version,
            stable_versions_file=stable_versions_file,
        )

        if self.EMBEDDED_PYTHON_ARCHITECTURE:
            arch = self.EMBEDDED_PYTHON_ARCHITECTURE.get_as_package_arch(
                package_type=self.PACKAGE_TYPE
            )
            requirements_package_architectures = [arch]
        else:

           requirements_package_architectures = OTHER_PACKAGES_ARCHITECTURES[self.PACKAGE_TYPE]

        description = "Dependency package of the Scalyr Agent package that provides Python interpreter and " \
                      "Pytohn wheels with required Python libraries."

        tmp_dir = tempfile.TemporaryDirectory()

        self.result_packages_path.mkdir(exist_ok=True)
        for arch in requirements_package_architectures:
            check_call_with_log(
                [
                    # fmt: off
                    "fpm",
                    "-t", self.PACKAGE_TYPE,
                    "-n", AGENT_REQUIREMENTS_PACKAGE_NAME,
                    "-a", arch,
                    "--depends", f"{self.get_python_package_name()} = {python_package_version}",
                    "--depends", f"{self.get_agent_wheels_package_name()} = {agent_wheels_package_version}",
                    "-v", version,
                    "--description", description,
                    *_FPM_COMMON_BUILD_ARGS,
                    "-C", str(tmp_dir.name),
                    "--verbose"
                    # fmt: on
                ],
                cwd=str(self.result_packages_path)
            )

        tmp_dir.cleanup()

    def publish_packages_to_packagecloud(
            self,
            packages_dir_path: pl.Path,
            token: str,
            repo_name: str,
            user_name: str,
    ):
        """
        Publish packages that are built by the 'build_packages' method.
        :param packages_dir_path: Path to a directory with target packages.
        :param token: Auth token to Packagecloud.
        :param repo_name: Target Packagecloud repo.
        :param user_name: Target Packagecloud user.
        """

        # Run in docker if needed.
        if self.runs_in_docker:
            self.run_in_docker(
                command_args=[
                    "publish",
                    "--packages-dir",
                    RunnerMappedPath(packages_dir_path),
                    "--token",
                    token,
                    "--repo-name",
                    repo_name,
                    "--user-name",
                    user_name
                ]
            )
            return

        # Set packagecloud's credentials file.
        config = {
            "url": "https://packagecloud.io",
            "token": token
        }

        config_file_path = pl.Path.home() / ".packagecloud"
        config_file_path.write_text(
            json.dumps(config)
        )

        packages_to_publish_file = packages_dir_path / "packages_to_publish.json"
        packages_to_publish = set(json.loads(
            packages_to_publish_file.read_text()
        ))

        for package_path in packages_dir_path.glob(f"*.{self.PACKAGE_TYPE}"):
            if package_path.name not in packages_to_publish:
                logger.info(f"Package {package_path.name} has been skipped since it's already in repo.")
                continue

            repo_paths = {
                "deb": f"{user_name}/{repo_name}/any/any",
                "rpm": f"{user_name}/{repo_name}/rpm_any/rpm_any",
            }

            check_call_with_log(
                [
                    "package_cloud",
                    "push",
                    repo_paths[self.PACKAGE_TYPE],
                    str(package_path)
                ]
            )

            logging.info(f"Package {package_path.name} is published.")

    def find_last_repo_package(
            self,
            package_name: str,
            token: str,
            user_name: str,
            repo_name: str,

    ) -> Optional[str]:
        """
        Find the most recent version of the given package in the repo.
        :param package_name: Name of the package.
        :param token: Packagecloud token
        :param repo_name: Target Packagecloud repo.
        :param user_name: Target Packagecloud user.
        :return: filename of the package if found, or None.
        """

        import requests
        from requests.auth import HTTPBasicAuth
        from requests.utils import parse_header_links

        auth = HTTPBasicAuth(token, "")

        param_filters = {
            "deb": "debs",
            "rpm": "rpms"
        }

        packages = []

        # First get the first page to get pagination links from response headers.
        with requests.Session() as s:
            resp = s.get(
                url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
                params={
                    "q": package_name,
                    "filter": param_filters[self.PACKAGE_TYPE],
                    "per_page": "250"
                },
                auth=auth
            )
            resp.raise_for_status()

            packages.extend(resp.json())

            # Iterate through other pages.
            while True:
                links = resp.headers.get("Link")

                if links is None:
                    break
                # Get link to the next page.

                links_dict = {
                    link["rel"]: link["url"] for link in parse_header_links(links)
                }

                next_page_url = links_dict.get("next")
                if next_page_url is None:
                    break

                resp = s.get(
                    url=next_page_url,
                    auth=auth
                )
                resp.raise_for_status()
                packages.extend(resp.json())

        filtered_packages = []
        distro_version = f"{self.PACKAGECLOUD_DISTRO}/{self.PACKAGECLOUD_DISTRO_VERSION}"

        for p in packages:
            # filter by package type
            if p["type"] != self.PACKAGE_TYPE:
                continue

            # filter by distro version.
            if distro_version != p["distro_version"]:
                continue

            # filter only packages with appropriate architecture
            _, _, arch, _ = self._parser_package_file_parts(
                package_file_name=p["filename"]
            )
            if arch != self.dependency_packages_arch:
                continue

            filtered_packages.append(p)

        if len(filtered_packages) == 0:
            logger.info(f"Could not find any package with name {package_name}")
            return None

        # sort packages by version and get the last one.
        sorted_packages = sorted(filtered_packages, key=operator.itemgetter("version"))

        last_package = sorted_packages[-1]

        return last_package["filename"]

    @staticmethod
    def download_package_from_repo(
            package_filename: str,
            output_dir: str,
            token: str,
            user_name: str,
            repo_name: str,
    ):
        """
        Download package file by the given filename.
        :param package_filename: Filename of the package.
        :param output_dir: Directory path to store the downloaded package.
        :param token: Packagecloud token
        :param repo_name: Target Packagecloud repo.
        :param user_name: Target Packagecloud user.
        :return: Path of the downloaded package.
        """

        # Query needed package info.
        import requests
        from requests.auth import HTTPBasicAuth

        auth = HTTPBasicAuth(token, "")

        # There's no need to use pagination, since we provide file name of an exact package and there has to be only
        # one occurrence.
        with requests.Session() as s:
            resp = s.get(
                url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
                params={
                    "q": f"{package_filename}",
                },
                auth=auth
            )
            resp.raise_for_status()

            found_packages = resp.json()

        assert len(found_packages) == 1, f"Expected number of found packages is 1, got {len(found_packages)}."
        last_package = found_packages[0]

        # Download found package file.
        auth = HTTPBasicAuth(token, "")
        with requests.Session() as s:
            resp = s.get(
                url=last_package["download_url"],
                auth=auth
            )
            resp.raise_for_status()

            output_dir_path = pl.Path(output_dir)
            output_dir_path.mkdir(parents=True, exist_ok=True)
            package_path = pl.Path(output_dir) / package_filename
            with package_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        return package_path


class DebDependencyPackagesBuilderX64_86(ManagedPackagesBuilder):
    EMBEDDED_PYTHON_ARCHITECTURE = Architecture.X86_64
    PACKAGE_TYPE = "deb"

class RpmDependencyPackagesBuilderX64_86(ManagedPackagesBuilder):
    EMBEDDED_PYTHON_ARCHITECTURE = Architecture.X86_64
    PACKAGE_TYPE = "rpm"


class DebDependencyPackagesBuilderArm64(ManagedPackagesBuilder):
    EMBEDDED_PYTHON_ARCHITECTURE = Architecture.ARM64
    PACKAGE_TYPE = "deb"


class RpmDependencyPackagesBuilderArm64(ManagedPackagesBuilder):
    EMBEDDED_PYTHON_ARCHITECTURE = Architecture.ARM64
    PACKAGE_TYPE = "rpm"


class DebDependencyPackagesBuilderSystemPython(ManagedPackagesBuilder):
    PACKAGE_TYPE = "deb"


class RpmDependencyPackagesSystemPython(ManagedPackagesBuilder):
    PACKAGE_TYPE = "rpm"


_ALL_DEPENDENCY_PACKAGES_BUILDERS = {
    "deb-amd64": DebDependencyPackagesBuilderX64_86,
    "deb-arm64": DebDependencyPackagesBuilderArm64,
    "rpm-x86_64": RpmDependencyPackagesBuilderX64_86,
    "rpm-aarch64": RpmDependencyPackagesBuilderArm64,
    "deb-system-python": DebDependencyPackagesBuilderSystemPython,
    "rpm-system-python": RpmDependencyPackagesSystemPython,
}


def _calculate_all_python_packages_checksum():
    sha256 = hashlib.sha256()
    for builder_name in sorted(_ALL_DEPENDENCY_PACKAGES_BUILDERS.keys()):
        builder_cls = _ALL_DEPENDENCY_PACKAGES_BUILDERS[builder_name]
        sha256.update(builder_cls.get_python_package_checksum().encode())

    return sha256.hexdigest()


_ALL_PYTHON_PACKAGES_CHECKSUM = _calculate_all_python_packages_checksum()


def _calculate_all_agent_wheels_packages_checksum():
    sha256 = hashlib.sha256()
    for builder_name in sorted(_ALL_DEPENDENCY_PACKAGES_BUILDERS.keys()):
        builder_cls = _ALL_DEPENDENCY_PACKAGES_BUILDERS[builder_name]
        sha256.update(builder_cls.get_agent_wheels_package_checksum().encode())

    return sha256.hexdigest()


_ALL_AGENT_WHEELS_PACKAGES_CHECKSUM = _calculate_all_agent_wheels_packages_checksum()


def _get_dependency_package_version_to_use(
        checksum: str,
        package_name: str,
        stable_versions_file_path: str = None
) -> Tuple[str, bool]:
    stable_version = None
    if stable_versions_file_path:
        versions = json.loads(pl.Path(stable_versions_file_path).read_text())
        stable_version = versions[package_name]

    if not stable_version:
        stable_version = "0+0"

    stable_iteration, stable_checksum = _parse_package_version_parts(version=stable_version)

    if checksum == stable_checksum:
        return stable_version, False
    else:
        new_iteration = stable_iteration + 1
        return f"{new_iteration}+{checksum}", True


def _parse_package_version_parts(version: str) -> Tuple[int, str]:
    """
    Deconstructs package version string and return tuple with version's iteration and checksum parts.
    """
    iteration, checksum = version.split("+")
    return int(iteration), checksum


class AgentPackageBuilder(BuilderBase):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_STEPS[Architecture.X86_64]
    PACKAGE_TYPE: str

    def build(
            self,
            stable_versions_file: str = None
    ):

        self.run_required()

        if self.runs_in_docker:
            args = ["build"]
            if stable_versions_file:
                args.extend([
                    "--stable-versions-file", RunnerMappedPath(stable_versions_file)
                ])
            self.run_in_docker(
                command_args=args
            )
            return

        agent_requirements_package_version, _ = _get_dependency_package_version_to_use(
            checksum=_ALL_AGENT_WHEELS_PACKAGES_CHECKSUM,
            package_name=AGENT_REQUIREMENTS_PACKAGE_NAME,
            stable_versions_file_path=stable_versions_file
        )

        agent_package_root = self.output_path / "agent_package_root"

        build_linux_fhs_agent_files(
            output_path=agent_package_root,
            copy_agent_source=True
        )

        install_root_executable_path = agent_package_root / f"usr/share/{AGENT_PACKAGE_NAME}/bin/scalyr-agent-2"
        install_root_executable_path.unlink()
        shutil.copy(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/scalyr-agent-2",
            install_root_executable_path
        )

        # Add config file
        add_config(
            SOURCE_ROOT / "config",
            agent_package_root / "etc/scalyr-agent-2"
        )

        # Copy init.d folder.
        shutil.copytree(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/init.d",
            agent_package_root / "etc/init.d",
            dirs_exist_ok=True
        )

        version = (SOURCE_ROOT / "VERSION").read_text().strip()

        description = "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics" \
                      " and log files and transmit them to Scalyr."

        scriptlets_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/install-scriptlets"

        packages_output = self.output_path / "packages"
        packages_output.mkdir()

        subprocess.check_call(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", "all",
                "-t", self.PACKAGE_TYPE,
                "-C", str(agent_package_root),
                "-n" "scalyr-agent-2",
                "-v", version,
                "--license", "Apache 2.0",
                "--vendor", "Scalyr",
                "--provides", "scalyr-agent-2",
                "--description", description,
                "--depends", "bash >= 3.2",
                "--depends", f"{AGENT_REQUIREMENTS_PACKAGE_NAME} = {agent_requirements_package_version}",
                "--url", "https://www.scalyr.com",
                "--deb-user", "root",
                "--deb-group", "root",
                "--rpm-user", "root",
                "--rpm-group", "root",
                #"--deb-changelog", "changelog-deb",
                #"--rpm-changelog", "changelog-rpm",
                "--after-install", scriptlets_path / "postinstall.sh",
                "--before-remove", scriptlets_path / "preuninstall.sh",
                "--deb-no-default-config-files",
                "--no-deb-auto-config-files",
                "--config-files", "/etc/scalyr-agent-2/agent.json",
                "--directories", "/usr/share/scalyr-agent-2",
                "--directories", "/var/lib/scalyr-agent-2",
                "--directories", "/var/log/scalyr-agent-2",
                "--rpm-use-file-permissions",
                "--deb-use-file-permissions",
                # NOTE: Sadly we can't use defattrdir since it breakes permissions for some other
                # directories such as /etc/init.d and we need to handle that in postinst :/
                # "  --rpm-auto-add-directories "
                # "  --rpm-defattrfile 640"
                # "  --rpm-defattrdir 751"
                "--verbose",
                # fmt: on
            ],
            cwd=str(packages_output)
        )

class DebAgentBuilder(AgentPackageBuilder):
    PACKAGE_TYPE = "deb"


class RpmAgentBuilder(AgentPackageBuilder):
    PACKAGE_TYPE = "rpm"


ALL_MANAGED_PACKAGE_BUILDERS: Dict[str, Type[Union[ManagedPackagesBuilder, AgentPackageBuilder]]] = {
    **_ALL_DEPENDENCY_PACKAGES_BUILDERS,
    "deb-agent": DebAgentBuilder,
    "rpm-agent": RpmAgentBuilder,
}