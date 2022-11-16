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
import json
import logging
import shutil
import subprocess
import tarfile
import argparse
import os
import pathlib as pl
from typing import List, Tuple

from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep
from agent_build_refactored.tools.constants import SOURCE_ROOT, EMBEDDED_PYTHON_VERSION
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_lfs_agent_files
from agent_build_refactored.managed_packages.dependency_packages import (
    BUILD_PYTHON_GLIBC_X86_64,
    DOWNLOAD_PYTHON_PACKAGE_FROM_PACKAGECLOUD,
    PYTHON_PACKAGE_VERSION,
    PYTHON_PACKAGE_VERSION_PATH,
    PYTHON_PACKAGE_NAME,

    BUILD_AGENT_LIBS_GLIBC_X86_64,

    PREPARE_TOOLSET_GLIBC_X86_64,
    AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
    EMBEDDED_PYTHON_SHORT_VERSION
)


class PythonPackageBuilder(Runner):
    PACKAGE_TYPE: str
    PACKAGE_ARCHITECTURE: str
    BUILD_PYTHON_STEP: ArtifactRunnerStep
    DOWNLOAD_PYTHON_PACKAGE: ArtifactRunnerStep
    BUILD_AGENT_LIBS_STEP: ArtifactRunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(PythonPackageBuilder, cls).get_all_required_steps()

        steps.extend([
            cls.BUILD_PYTHON_STEP,
            cls.DOWNLOAD_PYTHON_PACKAGE,
            cls.BUILD_AGENT_LIBS_STEP
        ])
        return steps

    @property
    def packages_output_path(self) -> pl.Path:
        return self.output_path / "packages"

    @property
    def packages_roots_path(self) -> pl.Path:
        return self.output_path / "packages_roots"

    @staticmethod
    def _get_package_version_parts(version: str) -> Tuple[int, str]:
        """
        Deconstructs package version string and return tuple with version's iteration and checksum parts.
        """
        iteration, checksum = version.split("_")
        return int(iteration), checksum

    def build_python_package(
            self,
    ):
        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        iteration, _ = self._get_package_version_parts(PYTHON_PACKAGE_VERSION)

        package_version = f"{iteration + 1}-{self.BUILD_PYTHON_STEP.checksum}"

        package_root = self.BUILD_PYTHON_STEP.get_output_directory(work_dir=self.work_dir) / "python",

        self.packages_output_path.mkdir(parents=True)

        check_call_with_log(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.PACKAGE_ARCHITECTURE,
                "-t", self.PACKAGE_TYPE,
                "-n", PYTHON_PACKAGE_NAME,
                "-v", package_version,
                "-C", str(package_root),
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
            ],
            cwd=str(self.packages_output_path)
        )

        found = list(self.packages_output_path.glob(
            f"{PYTHON_PACKAGE_NAME}_{package_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))

        assert len(found) == 1, f"Number of result Python packages has to be 1, got {len(found)}"

        return found[0]

    def build_packages(self):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=["build"]
                # python_executable=f"/usr/libexec/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/scalyr-agent-2-python3"
            )
            return

        packages_to_publish = []

        _, python_version_checksum = self._get_package_version_parts(PYTHON_PACKAGE_VERSION)

        python_package_file_path = None

        if python_version_checksum == self.BUILD_PYTHON_STEP.checksum:
            # If checksum of the build python step is the same as the checksum from the PYTHON_PACKAGE_VERSION,
            # then the Python package files haven't been changed, and it may be already published, so we try
            # to find that published package.
            pass

        if python_package_file_path is None:
            python_package_file_path = self.build_python_package()
            packages_to_publish.append(python_package_file_path.name)

        packages_to_publish_file_path = self.packages_output_path / "packages_to_publish.json"

        packages_to_publish_file_path.write_text(
            json.dumps(
                packages_to_publish,
                indent=4
            )
        )

    def publish_packages_to_packagecloud(
            self,
            packages_dir_path: pl.Path
    ):
        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=["publish"]
            )
            return
        packages_to_publish_path = packages_dir_path / "packages_to_publish.json"
        package_to_publish = json.loads(
            packages_to_publish_path.read_text()
        )

        config = {
            "url":"https://packagecloud.io",
            "token":"50552e5ef4df6c425e24d1213564910f1990c5fd25f2c4f4"
        }

        config_file_path = pl.Path.home() / ".packagecloud"
        config_file_path.write_text(
            json.dumps(config)
        )

        for package_file_name in package_to_publish:
            package_path = packages_dir_path / package_file_name

            if self.PACKAGE_TYPE == "deb":
                check_call_with_log(
                    [
                        "package_cloud",
                        "push",
                        "ArthurSentinelone/DataSetAgent/any/any",
                        str(package_path)
                    ]
                )

    def check_version_files_up_to_date(self):

        failed = False

        _, python_package_checksum = self._get_package_version_parts(PYTHON_PACKAGE_VERSION)

        if self.BUILD_PYTHON_STEP.checksum != python_package_checksum:
            logging.error(
                "Current Python package version does not match version in the "
                "PYTHON_PACKAGE_VERSION file"
            )

        if failed:
            logging.error("Please update version files and try again.")
            exit(1)

    def update_version_files(self):
        iteration, python_package_checksum = self._get_package_version_parts(PYTHON_PACKAGE_VERSION)

        if self.BUILD_PYTHON_STEP.checksum != python_package_checksum:
            PYTHON_PACKAGE_VERSION_PATH.write_text(
                f"{iteration + 1}-{self.BUILD_PYTHON_STEP.checksum}"
            )
            logging.info(f"The {PYTHON_PACKAGE_VERSION_PATH} file is updated.")


    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(PythonPackageBuilder, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command", required=True)

        build_packages_parser = subparsers.add_parser("build")

        build_packages_parser.add_argument(
            "--build-for",
            dest="build_for"
        )

        build_packages_parser.add_argument(
            "--version",
            dest="version",
        )

        publish_packages_parser = subparsers.add_parser("publish")
        publish_packages_parser.add_argument(
            "--packages-dir",
            dest="packages_dir",
            required=True,
            help="Path to a directory with packages to publish."
        )

        subparsers.add_parser(
            "check-version-files-up-to-date"
        )

        subparsers.add_parser(
            "update-version-files"
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
            builder.build_packages()

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
                packages_dir_path=pl.Path(args.packages_dir)
            )

        elif args.command == "check-version-files-up-to-date":
            builder.check_version_files_up_to_date()

        elif args.command == "update-version-files":
            builder.update_version_files()


class DebPythonPackageBuilderX64(PythonPackageBuilder):
    # BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"
    BUILD_PYTHON_STEP = BUILD_PYTHON_GLIBC_X86_64
    DOWNLOAD_PYTHON_PACKAGE = DOWNLOAD_PYTHON_PACKAGE_FROM_PACKAGECLOUD
    BUILD_AGENT_LIBS_STEP = BUILD_AGENT_LIBS_GLIBC_X86_64


MANAGED_PACKAGE_BUILDERS = {
    "deb-x64": DebPythonPackageBuilderX64
}