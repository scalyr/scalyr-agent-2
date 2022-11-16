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
from typing import List, Tuple, Optional

from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep
from agent_build_refactored.tools.constants import SOURCE_ROOT, EMBEDDED_PYTHON_VERSION
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_lfs_agent_files
from agent_build_refactored.managed_packages.dependency_packages import (
    BUILD_PYTHON_GLIBC_X86_64,
    DOWNLOAD_PYTHON_PACKAGE_FROM_PACKAGECLOUD,
    PACKAGES_VERSIONS,
    PACKAGES_VERSIONS_PATH,
    PYTHON_PACKAGE_NAME,

    BUILD_AGENT_LIBS_GLIBC_X86_64,
    DOWNLOAD_AGENT_LIBS_PACKAGE_FROM_PACKAGECLOUD,
    AGENT_LIBS_PACKAGE_NAME,

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
    DOWNLOAD_AGENT_LIBS_PACKAGE: ArtifactRunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(PythonPackageBuilder, cls).get_all_required_steps()

        steps.extend([
            cls.BUILD_PYTHON_STEP,
            cls.DOWNLOAD_PYTHON_PACKAGE,
            cls.BUILD_AGENT_LIBS_STEP,
            cls.DOWNLOAD_AGENT_LIBS_PACKAGE
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
        iteration, checksum = version.split("-")
        return int(iteration), checksum

    @staticmethod
    def _parse_version_from_package_file_name(package_file_name: str):
        filename, _ = package_file_name.split(".")
        _, version, _ = filename.split("_")
        return version

    def get_package_version(self, package: str):
        return PACKAGES_VERSIONS[package][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE]

    def build_python_package(
            self,
            increment_iteration: bool
    ):
        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        iteration, _ = self._get_package_version_parts(
            version=self.get_package_version(package="python")
        )

        if increment_iteration:
            iteration += 1

        package_version = f"{iteration}-{self.BUILD_PYTHON_STEP.checksum}"

        package_root = self.BUILD_PYTHON_STEP.get_output_directory(work_dir=self.work_dir) / "python"

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

    def build_agent_libs_package(
            self,
            increment_iteration: bool,
            python_package_version: str
    ):
        description = "Dependency package which provides Python requirement libraries which are used by the agent " \
                      "from the 'scalyr-agent-2 package'"

        iteration, _ = self._get_package_version_parts(
            version=self.get_package_version("agent_libs")
        )

        if increment_iteration:
            iteration += 1

        package_version = f"{iteration}-{self.BUILD_AGENT_LIBS_STEP.checksum}"

        package_root = self.BUILD_AGENT_LIBS_STEP.get_output_directory(work_dir=self.work_dir) / "agent_libs"

        check_call_with_log(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.PACKAGE_ARCHITECTURE,
                "-t", self.PACKAGE_TYPE,
                "-n", AGENT_LIBS_PACKAGE_NAME,
                "-v", package_version,
                "-C", str(package_root),
                "--license", '"Apache 2.0"',
                "--vendor", "Scalyr %s",
                "--provides", "scalyr-agent-2-dependencies",
                "--description", description,
                "--depends", "bash >= 3.2",
                "--depends", f"scalyr-agent-python3 = {python_package_version}",
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
            f"{AGENT_LIBS_PACKAGE_NAME}_{package_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))

        assert len(found) == 1, f"Number of result agent_libs packages has to be 1, got {len(found)}"

        return found[0]

    def _is_package_changed(self, package: str, build_step_checksum: str):
        current_version = self.get_package_version(package)
        _, current_version_checksum = self._get_package_version_parts(current_version)
        return current_version_checksum != build_step_checksum

    def _look_for_existing_package(self, package: str) -> Optional[pl.Path]:
        if package == "python":
            package_name = PYTHON_PACKAGE_NAME
            build_step = self.BUILD_PYTHON_STEP
            download_step = self.DOWNLOAD_PYTHON_PACKAGE
        elif package == "agent_libs":
            package_name = AGENT_LIBS_PACKAGE_NAME
            build_step = self.BUILD_AGENT_LIBS_STEP
            download_step = self.DOWNLOAD_AGENT_LIBS_PACKAGE
        else:
            raise ValueError(f"Invalid package type {package}")

        if self._is_package_changed(
                package=package, build_step_checksum=build_step.checksum
        ):
            return None

        # If checksum of the build step is the same as the checksum from the PACKAGES_VERSIONS file,
        # then the package files haven't been changed, and it may be already published, so we try
        # to find that published package.
        output = download_step.get_output_directory(work_dir=self.work_dir)
        current_version = self.get_package_version(package)
        found = list(output.glob(
            f"{package_name}_{current_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))
        if len(found) > 1:
            raise Exception(f"Number of downloaded {package} packages can be 1 or 0, got {len(found)}")

        if len(found) == 0:
            return None

        return found[0]

    def build_packages(self):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=["build"]
                # python_executable=f"/usr/libexec/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/scalyr-agent-2-python3"
            )
            return

        self.packages_output_path.mkdir(parents=True)

        packages_to_publish = []

        python_package_file_path = self._look_for_existing_package(
            package="python"
        )

        if python_package_file_path is None:
            increment_iteration = self._is_package_changed(
                package="python", build_step_checksum=self.BUILD_PYTHON_STEP.checksum
            )
            python_package_file_path = self.build_python_package(
                increment_iteration=increment_iteration
            )
            packages_to_publish.append(python_package_file_path.name)
            logging.info(f"Package {python_package_file_path.name} is built.")

        shutil.copy(
            python_package_file_path,
            self.packages_output_path
        )

        # Build or reuse agent_libs package.

        agent_libs_package_file_path = self._look_for_existing_package(
            package="agent_libs"
        )

        if agent_libs_package_file_path is None:
            increment_iteration = self._is_package_changed(
                package="agent_libs", build_step_checksum=self.BUILD_AGENT_LIBS_STEP.checksum
            )

            python_package_version = self._parse_version_from_package_file_name(
                package_file_name=python_package_file_path.name
            )
            agent_libs_package_file_path = self.build_agent_libs_package(
                increment_iteration=increment_iteration,
                python_package_version=python_package_version
            )
            packages_to_publish.append(agent_libs_package_file_path.name)
            logging.info(f"Package {agent_libs_package_file_path.name} is built.")

        shutil.copy(
            agent_libs_package_file_path,
            self.packages_output_path
        )

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

        published_packages_count = 0
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

            logging.info(f"Package {package_file_name} is published.")
            published_packages_count += 1

        if published_packages_count > 0:
            logging.info(f"{published_packages_count} packages are published.")
        else:
            logging.warning(f"No packages are published.")

    def check_package_version_file_up_to_date(self, package: str):

        failed = False

        current_version = PACKAGES_VERSIONS["python"][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE]
        _, python_package_checksum = self._get_package_version_parts(current_version)

        if self.BUILD_PYTHON_STEP.checksum != python_package_checksum:
            logging.error(
                f"Current version of the {package} {self.PACKAGE_TYPE} {self.PACKAGE_ARCHITECTURE} package does not match "
                f"version in the {PACKAGES_VERSIONS_PATH} file"
            )
            failed = True

        if failed:
            logging.error("Please update version file and try again.")
            exit(1)

        logging.info("All package version files are up to date.")

    def update_package_version_file(self, package: str):
        iteration, python_package_checksum = self._get_package_version_parts(
            version=self.get_python_package_version()
        )
        if self.BUILD_PYTHON_STEP.checksum != python_package_checksum:
            new_package_versions = PACKAGES_VERSIONS.copy()

            new_version = f"{iteration + 1}-{self.BUILD_PYTHON_STEP.checksum}"
            new_package_versions[package][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE] = new_version

            PACKAGES_VERSIONS_PATH.write_text(
                json.dumps(
                    new_package_versions,
                    sort_keys=True,
                    indent=4
                )
            )
            logging.info(f"The {PACKAGES_VERSIONS_PATH} file is updated.")


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


class DebPythonPackageBuilderX64(PythonPackageBuilder):
    # BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"
    BUILD_PYTHON_STEP = BUILD_PYTHON_GLIBC_X86_64
    DOWNLOAD_PYTHON_PACKAGE = DOWNLOAD_PYTHON_PACKAGE_FROM_PACKAGECLOUD
    BUILD_AGENT_LIBS_STEP = BUILD_AGENT_LIBS_GLIBC_X86_64
    DOWNLOAD_AGENT_LIBS_PACKAGE = DOWNLOAD_AGENT_LIBS_PACKAGE_FROM_PACKAGECLOUD


MANAGED_PACKAGE_BUILDERS = {
    "deb-x64": DebPythonPackageBuilderX64
}


class AllPackagesVersionTracker(Runner):

    def check_version_files_up_to_date(self):
        for builder_cls in MANAGED_PACKAGE_BUILDERS.values():
            builder = builder_cls(work_dir=self.work_dir)
            builder.check_package_version_file_up_to_date(
                package="python"
            )

    def update_version_files(self):
        for builder_cls in MANAGED_PACKAGE_BUILDERS.values():
            builder = builder_cls(work_dir=self.work_dir)
            builder.update_package_version_file(
                package="python"
            )

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(AllPackagesVersionTracker, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command", required=True)

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
        super(AllPackagesVersionTracker, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "check-version-files-up-to-date":
            builder.check_version_files_up_to_date()

        elif args.command == "update-version-files":
            builder.update_version_files()
