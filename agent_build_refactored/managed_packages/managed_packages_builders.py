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
from typing import List, Tuple, Optional, Dict


from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep
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
        iteration, checksum = version.split("-")
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


    def build_python_package(
            self,
            increment_iteration: bool
    ):
        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        repo_package_filename = self.get_repo_package_filename(PYTHON_PACKAGE_NAME)
        repo_package_version = self._parse_version_from_package_file_name(repo_package_filename)

        build_step = self.BUILD_STEPS[PYTHON_PACKAGE_NAME]

        if increment_iteration:
            iteration, _ = self._parse_package_version_parts(
                version=repo_package_version
            )
            iteration += 1
            new_package_version = f"{iteration}-{build_step.checksum}"
        else:
            new_package_version = repo_package_version

        package_root = build_step.get_output_directory(work_dir=self.work_dir) / "python"

        check_call_with_log(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.PACKAGE_ARCHITECTURE,
                "-t", self.PACKAGE_TYPE,
                "-n", PYTHON_PACKAGE_NAME,
                "-v", new_package_version,
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
            f"{PYTHON_PACKAGE_NAME}_{new_package_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
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

        repo_package_filename = self.get_repo_package_filename(AGENT_LIBS_PACKAGE_NAME)
        repo_package_version = self._parse_version_from_package_file_name(repo_package_filename)

        build_step = self.BUILD_STEPS[AGENT_LIBS_PACKAGE_NAME]

        if increment_iteration:
            iteration, _ = self._parse_package_version_parts(
                version=repo_package_version
            )
            iteration += 1
            new_package_version = f"{iteration}-{build_step.checksum}"
        else:
            new_package_version = repo_package_version

        build_step = self.BUILD_STEPS[AGENT_LIBS_PACKAGE_NAME]

        package_root = build_step.get_output_directory(work_dir=self.work_dir) / "agent_libs"

        check_call_with_log(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.PACKAGE_ARCHITECTURE,
                "-t", self.PACKAGE_TYPE,
                "-n", AGENT_LIBS_PACKAGE_NAME,
                "-v", new_package_version,
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
            f"{AGENT_LIBS_PACKAGE_NAME}_{new_package_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
        ))

        assert len(found) == 1, f"Number of result agent_libs packages has to be 1, got {len(found)}"

        return found[0]

    def build_packages(
            self,
            token: str,
            repo_name: str,
            user_name: str,
            reuse_existing_repo_packages: bool = False,

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

        packages_to_publish = []

        python_package_path = None

        if reuse_existing_repo_packages:
            python_package_path = self.download_package_from_packagecloud(
                package_name=PYTHON_PACKAGE_NAME,
                token=token,
                repo_name=repo_name,
                user_name=user_name,
            )

        if python_package_path is None:
            if reuse_existing_repo_packages:
                increment_iteration = False
            else:
                increment_iteration = True

            python_package_path = self.build_python_package(
                increment_iteration=increment_iteration
            )
            packages_to_publish.append(python_package_path.name)
            logging.info(f"Package {python_package_path.name} is built.")

        # Build or reuse agent_libs package.

        agent_libs_package_path = None

        if reuse_existing_repo_packages:
            agent_libs_package_path = self.download_package_from_packagecloud(
                package_name=AGENT_LIBS_PACKAGE_NAME,
                token=token,
                repo_name=repo_name,
                user_name=user_name,
            )

        if agent_libs_package_path is None:
            if reuse_existing_repo_packages:
                increment_iteration = False
            else:
                increment_iteration = True

            python_package_version = self._parse_version_from_package_file_name(
                package_file_name=python_package_path.name
            )

            agent_libs_package_file_path = self.build_agent_libs_package(
                increment_iteration=increment_iteration,
                python_package_version=python_package_version
            )
            packages_to_publish.append(agent_libs_package_file_path.name)
            logging.info(f"Package {agent_libs_package_file_path.name} is built.")

        packages_to_publish_file_path = self.packages_output_path / "packages_to_publish.json"

        packages_to_publish_file_path.write_text(
            json.dumps(
                packages_to_publish,
                indent=4
            )
        )

    def publish_packages_to_packagecloud(
            self,
            packages_dir_path: pl.Path,
            token: str,
            repo_name: str,
            user_name: str,
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
            "url": "https://packagecloud.io",
            "token": token
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
                        f"{user_name}/{repo_name}/any/any",
                        str(package_path)
                    ]
                )

            logging.info(f"Package {package_file_name} is published.")
            published_packages_count += 1

        if published_packages_count > 0:
            logging.info(f"{published_packages_count} packages are published.")
        else:
            logging.warning(f"No packages are published.")


    def check_repo_packages_file_is_up_to_date(self, package_name: str):

        build_step = self.BUILD_STEPS[package_name]

        repo_package_filename = PACKAGECLOUD_PACKAGES[package_name][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE]
        repo_package_version = self._parse_version_from_package_file_name(repo_package_filename)
        _, repo_package_checksum = self._parse_package_version_parts(repo_package_version)

        if build_step.checksum != repo_package_checksum:
            logging.error(
                f"Current version of the {package_name} {self.PACKAGE_TYPE} {self.PACKAGE_ARCHITECTURE} package does "
                f"not match version in the {PACKAGECLOUD_PACKAGES_VERSIONS_PATH} file"
            )
            logging.error(
                "Please update this file by running the "
                "'agent_build_refactored/scripts/runner_helper.py "
                "agent_build_refactored.managed_packages.managed_packages_builders.AllPackagesVersionTracker "
                "update-version-files"
            )
            exit(1)

    def update_repo_package_file(self, package_name: str):

        repo_package_file_name = self.get_repo_package_filename(package_name)
        repo_package_version = self._parse_version_from_package_file_name(
            package_file_name=repo_package_file_name
        )

        iteration, current_package_checksum = self._parse_package_version_parts(
            version=repo_package_version
        )

        build_step = self.BUILD_STEPS[package_name]

        if build_step.checksum != current_package_checksum:
            new_packagecloud_packages = PACKAGECLOUD_PACKAGES.copy()

            new_version = f"{iteration + 1}-{build_step.checksum}"
            new_filename = f"{package_name}_{new_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
            new_packagecloud_packages[package_name][self.PACKAGE_TYPE][self.PACKAGE_ARCHITECTURE] = new_filename

            PACKAGECLOUD_PACKAGES_VERSIONS_PATH.write_text(
                json.dumps(
                    new_packagecloud_packages,
                    sort_keys=True,
                    indent=4
                )
            )
            logging.info(f"The {PACKAGECLOUD_PACKAGES_VERSIONS_PATH} file is updated.")

    def download_package_from_packagecloud(
            self,
            package_name: str,
            token: str,
            user_name: str,
            repo_name: str,

    ) -> Optional[pl.Path]:


        import requests
        from requests.auth import HTTPBasicAuth

        repo_package_file_name = self.get_repo_package_filename(
            package_name=package_name
        )

        auth = HTTPBasicAuth(token, "")

        with requests.Session() as s:
            resp = s.get(
                url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
                params={
                    "q": repo_package_file_name
                },
                auth=auth
            )

        resp.raise_for_status()
        packages = resp.json()

        if len(packages) == 0:
            logger.info(f"Package {repo_package_file_name} is not in the Packagecloud repository.")
            return None

        download_url = packages[0]["download_url"]

        package_path = self.packages_output_path / repo_package_file_name

        with requests.Session() as s:
            resp = s.get(
                url=download_url,
                auth=auth,
                stream=True
            )
            resp.raise_for_status()
            with package_path.open("wb") as f:
                shutil.copyfileobj(resp.raw, f)


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
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"

    BUILD_STEPS = {
        PYTHON_PACKAGE_NAME: BUILD_PYTHON_GLIBC_X86_64,
        AGENT_LIBS_PACKAGE_NAME: BUILD_AGENT_LIBS_GLIBC_X86_64
    }


ALL_MANAGED_PACKAGE_BUILDERS = {
    "deb-amd64": DebPythonPackageBuilderX64
}


class AllPackagesVersionTracker(Runner):

    def check_repo_package_file_is_up_to_date(self):
        for builder_cls in ALL_MANAGED_PACKAGE_BUILDERS.values():
            builder = builder_cls(work_dir=self.work_dir)
            builder.check_repo_packages_file_is_up_to_date(
                package_name=PYTHON_PACKAGE_NAME
            )
            builder.check_repo_packages_file_is_up_to_date(
                package_name=AGENT_LIBS_PACKAGE_NAME
            )

        logging.info("All package version files are up to date.")

    def update_repo_packages_file(self):
        for builder_cls in ALL_MANAGED_PACKAGE_BUILDERS.values():
            builder = builder_cls(work_dir=self.work_dir)
            builder.update_repo_package_file(
                package_name=PYTHON_PACKAGE_NAME
            )
            builder.update_repo_package_file(
                package_name=AGENT_LIBS_PACKAGE_NAME
            )

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(AllPackagesVersionTracker, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command", required=True)

        subparsers.add_parser(
            "check_repo_package_file_is_up_to_date"
        )

        subparsers.add_parser(
            "update_repo_packages_file"
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(AllPackagesVersionTracker, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "check_repo_package_file_is_up_to_date":
            builder.check_repo_package_file_is_up_to_date()

        elif args.command == "update_repo_packages_file":
            builder.update_repo_packages_file()
