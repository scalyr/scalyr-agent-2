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


import datetime
import hashlib
import json
import logging
import shutil
import subprocess
import tarfile
import argparse
import os
import pathlib as pl
from typing import List, Tuple, Optional, Dict


from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep, RunnerMappedPath
from agent_build_refactored.tools.constants import SOURCE_ROOT, EMBEDDED_PYTHON_VERSION
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_lfs_agent_files
from agent_build_refactored.managed_packages.dependency_packages import (
    BUILD_PYTHON_GLIBC_X86_64,
    PACKAGECLOUD_PACKAGES,
    PACKAGECLOUD_PACKAGES_VERSIONS_PATH,
    PYTHON_PACKAGE_NAME,

    BUILD_AGENT_LIBS_GLIBC_X86_64,
    AGENT_LIBS_PACKAGE_NAME,

    PREPARE_TOOLSET_GLIBC_X86_64,
    AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
    EMBEDDED_PYTHON_SHORT_VERSION
)

logger = logging.getLogger(__name__)


class PythonPackageBuilder(Runner):
    PACKAGE_TYPE: str
    PACKAGE_ARCHITECTURE: str

    BUILD_STEPS: Dict[str, ArtifactRunnerStep]

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(PythonPackageBuilder, cls).get_all_required_steps()

        steps.extend([
            *cls.BUILD_STEPS.values(),
        ])
        return steps

    @property
    def packages_output_path(self) -> pl.Path:
        return self.output_path / "packages"

    @property
    def packages_roots_path(self) -> pl.Path:
        return self.output_path / "packages_roots"

    @staticmethod
    def _parse_package_version_parts(version: str) -> Tuple[int, str]:
        """
        Deconstructs package version string and return tuple with version's iteration and checksum parts.
        """
        iteration, checksum = version.split("+")
        return int(iteration), checksum

    @staticmethod
    def _parse_version_from_package_file_name(package_file_name: str):
        filename, _ = package_file_name.split(".")
        _, version, _ = filename.split("_")
        return version

    def get_repo_package_filename(
        self,
        package_name: str
    ) -> str:

        return PACKAGECLOUD_PACKAGES[package_name][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE]

    @property
    def python_package_build_cmd_args(self) -> List[str]:

        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        return [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.PACKAGE_ARCHITECTURE,
                "-t", self.PACKAGE_TYPE,
                "-n", PYTHON_PACKAGE_NAME,
                "--license", '"Apache 2.0"',
                "--vendor", "Scalyr %s",
                "--provides", "scalyr-agent-dependencies",
                "--description", description,
                "--depends", "bash >= 3.2",
                "--url", "https://www.scalyr.com",
                "--deb-user", "root",
                "--deb-group", "root",
                "--rpm-user", "root",
                "--rpm-group", "root",
                # fmt: on
            ]

    @property
    def agent_libs_build_command_args(self) -> List[str]:

        description = "Dependency package which provides Python requirement libraries which are used by the agent " \
                      "from the 'scalyr-agent-2 package'"

        return [
            # fmt: off
            "fpm",
            "-s", "dir",
            "-a", self.PACKAGE_ARCHITECTURE,
            "-t", self.PACKAGE_TYPE,
            "-n", AGENT_LIBS_PACKAGE_NAME,
            "--license", '"Apache 2.0"',
            "--vendor", "Scalyr %s",
            "--provides", "scalyr-agent-2-dependencies",
            "--description", description,
            "--depends", "bash >= 3.2",
            "--url", "https://www.scalyr.com",
            "--deb-user", "root",
            "--deb-group", "root",
            "--rpm-user", "root",
            "--rpm-group", "root",
            # fmt: on
        ]

    def _get_package_checksum(
            self,
            package_name: str,
    ):
        build_step = self.BUILD_STEPS[package_name]

        if package_name == PYTHON_PACKAGE_NAME:
            build_command_args = self.python_package_build_cmd_args
        else:
            build_command_args = self.agent_libs_build_command_args

        sha256 = hashlib.sha256()
        sha256.update(build_step.checksum.encode())

        for arg in build_command_args:
            sha256.update(arg.encode())

        return sha256.hexdigest()

    def build_python_package(
            self,
            version: str
    ):

        build_step = self.BUILD_STEPS[PYTHON_PACKAGE_NAME]
        package_root = build_step.get_output_directory(work_dir=self.work_dir) / "python"

        check_call_with_log(
            [
                *self.python_package_build_cmd_args,
                "-v", version,
                "-C", str(package_root),
            ],
            cwd=str(self.packages_output_path)
        )

        found = list(self.packages_output_path.glob(
            f"{PYTHON_PACKAGE_NAME}_{version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))

        assert len(found) == 1, f"Number of result Python packages has to be 1, got {len(found)}"

        return found[0]

    def build_agent_libs_package(
            self,
            token: str,
            repo_name: str,
            user_name: str,
            reuse_existing_python_package: bool,
            version: str
    ):

        current_python_package_checksum = self._get_package_checksum(
            package_name=PYTHON_PACKAGE_NAME
        )

        if reuse_existing_python_package:
            recent_python_package_version = self.find_most_recent_package_from_packagecloud(
                package_name=PYTHON_PACKAGE_NAME,
                package_checksum=self._get_package_checksum(PYTHON_PACKAGE_NAME),
                token=token,
                repo_name=repo_name,
                user_name=user_name,
            )

            if recent_python_package_version is None:
                recent_python_package_version = "0+0"

            repo_python_package_iteration, repo_python_package_checksum = self._parse_package_version_parts(
                version=recent_python_package_version
            )

            if current_python_package_checksum == repo_python_package_checksum:
                python_package_version = recent_python_package_version
                build_python_package = False
            else:
                new_iteration = repo_python_package_iteration + 1
                python_package_version = f"{new_iteration}+{current_python_package_checksum}"
                build_python_package = True
        else:
            python_package_version = f"dev+{current_python_package_checksum}"
            build_python_package = True

        if build_python_package:
            self.build_python_package(
                version=python_package_version
            )

        build_step = self.BUILD_STEPS[AGENT_LIBS_PACKAGE_NAME]
        package_root = build_step.get_output_directory(work_dir=self.work_dir) / "agent_libs"

        check_call_with_log(
            [
                *self.agent_libs_build_command_args,
                "-v", version,
                "-C", str(package_root),
                "--depends", f"scalyr-agent-python3 = {python_package_version}",
            ],
            cwd=str(self.packages_output_path)
        )

        found = list(self.packages_output_path.glob(
            f"{AGENT_LIBS_PACKAGE_NAME}_{version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))

        assert len(found) == 1, f"Number of result agent_libs packages has to be 1, got {len(found)}"

        return found[0]

    def build_packages(
            self,
            token: str,
            repo_name: str,
            user_name: str,
            reuse_existing_repo_packages: bool,
            python_package_file_path: pl.Path = None,
            agent_libs_package_file_path: pl.Path = None

    ):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=[
                    "build",
                    "--user-name",
                    user_name,
                    "--repo-name",
                    repo_name,
                    "--token",
                    token,
                    "--reuse-existing-repo-packages",
                    reuse_existing_repo_packages
                ]
            )
            return

        self.packages_output_path.mkdir(parents=True)

        current_agent_libs_package_checksum = self._get_package_checksum(
            package_name=AGENT_LIBS_PACKAGE_NAME
        )

        if reuse_existing_repo_packages:
            recent_agent_libs_package_version = self.find_most_recent_package_from_packagecloud(
                package_name=AGENT_LIBS_PACKAGE_NAME,
                package_checksum=self._get_package_checksum(AGENT_LIBS_PACKAGE_NAME),
                token=token,
                repo_name=repo_name,
                user_name=user_name,
            )

            if recent_agent_libs_package_version is None:
                recent_agent_libs_package_version = f"0+0"

            recent_package_iteration, recent_package_checksum = self._parse_package_version_parts(
                version=recent_agent_libs_package_version
            )

            if current_agent_libs_package_checksum == recent_package_checksum:
                agent_libs_package_version = recent_agent_libs_package_version
                build_agent_libs_package = False
            else:
                new_iteration = recent_package_iteration + 1
                agent_libs_package_version = f"{new_iteration}+{current_agent_libs_package_checksum}"
                build_agent_libs_package = True
        else:
            agent_libs_package_version = f"dev+{current_agent_libs_package_checksum}"
            build_agent_libs_package = True

        if build_agent_libs_package:
            self.build_agent_libs_package(
                version=agent_libs_package_version,
                token=token,
                repo_name=repo_name,
                user_name=user_name,
                reuse_existing_python_package=reuse_existing_repo_packages
            )


        return

    def publish_packages_to_packagecloud(
            self,
            packages_dir_path: pl.Path,
            token: str,
            repo_name: str,
            user_name: str,
    ):

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

    def find_most_recent_package_from_packagecloud(
            self,
            package_name: str,
            package_checksum: str,
            token: str,
            user_name: str,
            repo_name: str,

    ) -> Optional[str]:

        import requests
        from requests.auth import HTTPBasicAuth

        auth = HTTPBasicAuth(token, "")

        if self.PACKAGE_TYPE == "deb":
            query_package_type_filter = "debs"
        else:
            raise Exception(f"Unknown package type {self.PACKAGE_TYPE}.")

        with requests.Session() as s:
            resp = s.get(
                url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
                params={
                    "q": f"{package_name}",
                    "filter": query_package_type_filter
                },
                auth=auth
            )

        resp.raise_for_status()
        packages = resp.json()

        if len(packages) == 0:
            logger.info(f"Package with checksum {package_checksum} is not in the Packagecloud repository.")
            return None

        recent_package = packages[-1]

        return recent_package["version"]

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(PythonPackageBuilder, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command")

        build_packages_parser = subparsers.add_parser("build")

        build_packages_parser.add_argument(
            "--build-for",
            dest="build_for"
        )

        build_packages_parser.add_argument(
            "--version",
            dest="version",
        )
        build_packages_parser.add_argument(
            "--token",
            required=True
        )

        build_packages_parser.add_argument(
            "--user-name",
            dest="user_name",
            required=True
        )

        build_packages_parser.add_argument(
            "--repo-name",
            dest="repo_name",
            required=True
        )

        build_packages_parser.add_argument(
            "--reuse-existing-repo-packages",
            dest="reuse_existing_repo_packages",
            default="false"
        )

        publish_packages_parser = subparsers.add_parser("publish")
        publish_packages_parser.add_argument(
            "--packages-dir",
            dest="packages_dir",
            required=True,
            help="Path to a directory with packages to publish."
        )
        publish_packages_parser.add_argument(
            "--token",
            required=True
        )

        publish_packages_parser.add_argument(
            "--user-name",
            dest="user_name",
            required=True
        )

        publish_packages_parser.add_argument(
            "--repo-name",
            dest="repo_name",
            required=True
        )


    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(PythonPackageBuilder, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "build":
            builder.build_packages(
                token=args.token,
                user_name=args.user_name,
                repo_name=args.repo_name,
                reuse_existing_repo_packages=args.reuse_existing_repo_packages == "true"
            )

            output_path = SOURCE_ROOT / "build"
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.copytree(
                builder.packages_output_path,
                output_path,
                dirs_exist_ok=True,
            )
        elif args.command == "publish":
            builder.publish_packages_to_packagecloud(
                packages_dir_path=pl.Path(args.packages_dir),
                token=args.token,
                user_name=args.user_name,
                repo_name=args.repo_name,
            )
        else:
            logging.error(f"Unknown command {args.command}.")
            exit(1)


class DebPythonPackageBuilderX64(PythonPackageBuilder):
    # BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"

    BUILD_STEPS = {
        PYTHON_PACKAGE_NAME: BUILD_PYTHON_GLIBC_X86_64,
        AGENT_LIBS_PACKAGE_NAME: BUILD_AGENT_LIBS_GLIBC_X86_64
    }


ALL_MANAGED_PACKAGE_BUILDERS = {
    "deb-amd64": DebPythonPackageBuilderX64
}