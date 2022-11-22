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


import hashlib
import json
import logging
import shutil
import subprocess
import argparse
import os
import pathlib as pl
from typing import List, Tuple, Optional, Dict


from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep, RunnerMappedPath, EnvironmentRunnerStep, DockerImageSpec,GitHubActionsSettings
from agent_build_refactored.tools.constants import SOURCE_ROOT, EMBEDDED_PYTHON_VERSION, DockerPlatform
from agent_build_refactored.tools import check_call_with_log

logger = logging.getLogger(__name__)


AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME = "scalyr-agent-2-dependencies"
PYTHON_PACKAGE_NAME = "scalyr-agent-python3"
AGENT_LIBS_PACKAGE_NAME = "scalyr-agent-libs"


PYTHON_PACKAGE_SSL_VERSION = "1.1.1k"
EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])


def create_build_dependencies_step(
        base_image: EnvironmentRunnerStep
) -> EnvironmentRunnerStep:
    """
    This function creates step that installsP Python build requirements, to a given environment.
    :param base_image: Environment step runner with the target environment.
    :return: Result step.
    """

    return EnvironmentRunnerStep(
        name="install_build_dependencies",
        script_path="agent_build_refactored/managed_packages/steps/install_build_dependencies.sh",
        base=base_image,
        environment_variables={
            "PERL_VERSION": "5.36.0",
            "ZX_VERSION": "5.2.6",
            "TEXTINFO_VERSION": "6.8",
            "M4_VERSION": "1.4.19",
            "LIBTOOL_VERSION": "2.4.6",
            "AUTOCONF_VERSION": "2.71",
            "AUTOMAKE_VERSION": "1.16",
            "HELP2MAN_VERSION": "1.49.2",
            "LZMA_VERSION": "4.32.7",
            "OPENSSL_VERSION": PYTHON_PACKAGE_SSL_VERSION,
            "LIBFFI_VERSION": "3.4.2",
            "UTIL_LINUX_VERSION": "2.38",
            "NCURSES_VERSION": "6.3",
            "LIBEDIT_VERSION": "20210910-3.1",
            "GDBM_VERSION": "1.23",
            "ZLIB_VERSION": "1.2.13",
            "BZIP_VERSION": "1.0.8",
            "RUST_VERSION": "1.63.0",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


def create_build_python_step(
        base_step: EnvironmentRunnerStep
):
    """
    Function that creates step instance that build Python interpreter.
    :param base_step: Step with environment where to build.
    :return: Result step.
    """
    return ArtifactRunnerStep(
        name="build_python",
        script_path="agent_build_refactored/managed_packages/steps/build_python.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/files/scalyr-agent-2-python3",
        ],
        base=base_step,
        environment_variables={
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "PYTHON_INSTALL_PREFIX": "/usr",
            "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


def create_build_agent_libs_step(
        base_step: EnvironmentRunnerStep,
        build_python_step: ArtifactRunnerStep
):
    """
    Function that creates step that installs agent requirement libraries.
    :param base_step: Step with environment where to build.
    :param build_python_step: Required step that builds Python.
    :return: Result step.
    """
    return ArtifactRunnerStep(
        name="build_agent_libs",
        script_path="agent_build_refactored/managed_packages/steps/build_agent_libs.sh",
        tracked_files_globs=[
            "agent_build/requirement-files/*.txt",
            "dev-requirements.txt"
        ],
        base=base_step,
        required_steps={
            "BUILD_PYTHON": build_python_step
        },
        environment_variables={
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "RUST_VERSION": "1.63.0",
            "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


# Step that prepares initial environment for X86_64 build environment.
INSTALL_GCC_7_GLIBC_X86_64 = EnvironmentRunnerStep(
        name="install_gcc_7",
        script_path="agent_build_refactored/managed_packages/steps/install_gcc_7.sh",
        base=DockerImageSpec(
            name="centos:6",
            platform=DockerPlatform.AMD64.value
        ),
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )
# Step that installs Python build requirements to the build environment.
INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64 = create_build_dependencies_step(
    base_image=INSTALL_GCC_7_GLIBC_X86_64
)

# Create step that builds Python interpreter.
BUILD_PYTHON_GLIBC_X86_64 = create_build_python_step(
    base_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64
)

# Create step that builds agent requirement libs.
BUILD_AGENT_LIBS_GLIBC_X86_64 = create_build_agent_libs_step(
    base_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64,
    build_python_step=BUILD_PYTHON_GLIBC_X86_64
)

# Create step that prepare environment with all needed tools.
PREPARE_TOOLSET_GLIBC_X86_64 = EnvironmentRunnerStep(
    name="prepare_toolset",
    script_path="agent_build_refactored/managed_packages/steps/prepare_toolset.sh",
    base=DockerImageSpec(
        name="ubuntu:22.04",
        platform=DockerPlatform.AMD64.value
    ),
    required_steps={
        "BUILD_PYTHON": BUILD_PYTHON_GLIBC_X86_64,
        "BUILD_AGENT_LIBS": BUILD_AGENT_LIBS_GLIBC_X86_64
    },
    environment_variables={
        "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
        "FPM_VERSION": "1.14.2",
        "PACKAGECLOUD_VERSION": "0.3.11",
        "USER_NAME": subprocess.check_output("whoami").decode().strip(),
        "USER_ID": str(os.getuid()),
        "USER_GID": str(os.getgid()),
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)


class PythonPackageBuilder(Runner):
    """
    Builder class that is responsible for the building of the Linux agent deb and rpm packages that are managed by package
        managers such as apt and yum.

    Besides building the agent package itself, it also builds dependency packages:
        - scalyr-agent-python3
        - scalyr-agent-libs

    These packages are needed to make agent package completely independent of a target system.


    The 'scalyr-agent-python3' package provides Python interpreter that is specially built to be used by the agemt.
        Its main feature that it is built against the oldest GLIBC possible, so it has to be enough to maintain
        only one build of the package in order to support all target systems.


    The 'scalyr-agent-libs' package provides requirement libraries for the agent, for example Python 'requests' or
        'orjson' libraries. It is intended to ship it separately from the 'scalyr-agent-python3' because we update
        agent's requirements much more often than Python interpreter.

    The structure of the mentioned packages has to guarantee that files of these packages does not interfere with
        files of local system Python interpreter. To achieve that, the dependency packages files are installed in their
        own 'sub-directories'

        /usr/libe/scalyr-agent-2-dependencies
        /usr/libexec/scalyr-agent-2-dependencies
        /usr/shared/scalyr-agent-2-dependencies
        /usr/include/scalyr-agent-2-dependencies

        and agent from the 'scalyr-agent-2' package has to use the
        '/usr/libexec/scalyr-agent-2-dependencies/scalyr-agent-2-python3' executable.

    This builder provides next functionality.
        'build_packages' - Build all needed packages.
    """

    # type of the package, aka 'deb' or 'rpm'
    PACKAGE_TYPE: str

    # package architecture, for example: amd64 for deb.
    PACKAGE_ARCHITECTURE: str

    # Instance of the step that builds filesystem for the python package.
    PYTHON_BUILD_STEP: ArtifactRunnerStep
    # Instance of the step that builds filesystem for the agent-libs package.
    AGENT_LIBS_BUILD_STEP: ArtifactRunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(PythonPackageBuilder, cls).get_all_required_steps()

        steps.extend([
            cls.PYTHON_BUILD_STEP,
            cls.AGENT_LIBS_BUILD_STEP
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

    def _parse_version_from_package_file_name(self, package_file_name: str):
        """
        Parse version of the package from its filename.
        """
        if self.PACKAGE_TYPE == "deb":
            # split filename to name and extension
            filename, _ = package_file_name.split(".")
            # then split name to name prefix, version and architecture.
            _, version, _ = filename.split("_")
            return version
        else:
            # split filename to name, arch, and extension
            filename, _, _ = package_file_name.split(".")
            # split with release
            prefix, _ = filename.rsplit("-", 1)
            # split with version
            _, version = prefix.rsplit("-", 1)
            return version

    @property
    def python_package_build_cmd_args(self) -> List[str]:
        """
        Returns list of arguments for the command that builds python package.
        """

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
        """
        Returns list of arguments for command that build agent-libs package.
        """

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
        """
        Get checksum of the package. We try to take into account every possible variable
            that may affect the result package.

        For now, those are:
            - checksum of the step that produces files for package.
            - command line arguments that are used to build the package.

        :param package_name:
        :return:
        """

        if package_name == PYTHON_PACKAGE_NAME:
            build_step = self.PYTHON_BUILD_STEP
            build_command_args = self.python_package_build_cmd_args
        else:
            build_step = self.AGENT_LIBS_BUILD_STEP
            build_command_args = self.agent_libs_build_command_args

        # Add checksum of the step that builds package files.
        sha256 = hashlib.sha256()
        sha256.update(build_step.checksum.encode())

        # Add arguments that are used to build package.
        for arg in build_command_args:
            sha256.update(arg.encode())

        return sha256.hexdigest()

    def _get_final_package_path_and_version(
            self,
            package_name: str,
            last_repo_package_file_path: pl.Path = None,
    ) -> Tuple[Optional[pl.Path], str]:
        """
        Get path to path and version of the final package to build.
        :param package_name: name of the package.
        :param last_repo_package_file_path: Path to a last package from the repo. If specified and there are no changes
            between current package and package from repo, then package from repo is used instead of building a new one.
        :return: Tuple with:
            - Path to the final package. None if package is not found in repo.
            - Version of the final package.
        """
        final_package_path = None

        current_package_checksum = self._get_package_checksum(
            package_name=package_name
        )

        if last_repo_package_file_path is None:
            # If there is no any recent version of the package in repo then build new version for the first package.
            final_package_version = f"1+{current_package_checksum}"
        else:
            # If there is a recent version of the package in the repo, then parse its checksum and compare it
            # with the checksum of the current package. If checksums are identical, then we can reuse
            # package version for the repo.
            last_repo_package_version = self._parse_version_from_package_file_name(
                package_file_name=last_repo_package_file_path.name
            )
            last_repo_package_iteration, last_repo_package_checksum = self._parse_package_version_parts(
                version=last_repo_package_version
            )
            if current_package_checksum == last_repo_package_checksum:
                final_package_version = last_repo_package_version
                final_package_path = last_repo_package_file_path
            else:
                # checksums are not identical, create new version of the package.
                final_package_version = f"{last_repo_package_iteration + 1}+{current_package_checksum}"

        return final_package_path, final_package_version

    def build_packages(
            self,
            last_repo_python_package_file: str = None,
            last_repo_agent_libs_package_file: str = None

    ):
        """
        Build needed packages.

        :param last_repo_python_package_file: Path to the python package file. If specified, then the python
            dependency package from this path will be reused instead of building a new one.
        :param last_repo_agent_libs_package_file: Path to the agent libs package file. If specified, then the agent-libs
            dependency package from this path will be reused instead of building a new one.
        """

        self.run_required()

        # Run inside the docker if needed.
        if self.runs_in_docker:
            command_args = ["build"]
            if last_repo_python_package_file:
                command_args.extend([
                    "--last-repo-python-package-file",
                    RunnerMappedPath(last_repo_python_package_file)
                ])

            if last_repo_agent_libs_package_file:
                command_args.extend([
                    "--last-repo-agent-libs-package-file",
                    RunnerMappedPath(last_repo_agent_libs_package_file)
                ])

            self.run_in_docker(command_args=command_args)
            return

        packages_to_publish = []

        last_repo_python_package_path = None
        last_repo_agent_libs_package_path = None

        # Check if there are packages to reuse provided.
        if last_repo_python_package_file:
            last_repo_python_package_path = pl.Path(last_repo_python_package_file)

        if last_repo_agent_libs_package_file:
            last_repo_agent_libs_package_path = pl.Path(last_repo_agent_libs_package_file)

        self.packages_output_path.mkdir(parents=True)

        # Get reused package from repo, in case current package is unchanged and it is already in repo.
        final_python_package_path, final_python_version = self._get_final_package_path_and_version(
            package_name=PYTHON_PACKAGE_NAME,
            last_repo_package_file_path=last_repo_python_package_path
        )

        # Python package is not found in repo, build it.
        if final_python_package_path is None:
            package_root = self.PYTHON_BUILD_STEP.get_output_directory(work_dir=self.work_dir) / "python"

            check_call_with_log(
                [
                    *self.python_package_build_cmd_args,
                    "-v", final_python_version,
                    "-C", str(package_root),
                ],
                cwd=str(self.packages_output_path)
            )
            if self.PACKAGE_TYPE == "deb":
                found = list(self.packages_output_path.glob(
                    f"{PYTHON_PACKAGE_NAME}_{final_python_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
                ))
            elif self.PACKAGE_TYPE == "rpm":
                found = list(self.packages_output_path.glob(
                    f"{PYTHON_PACKAGE_NAME}-{final_python_version}-1.{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
                ))
            else:
                raise Exception(f"Unknown package type {self.PACKAGE_TYPE}")

            assert len(found) == 1, f"Number of result Python packages has to be 1, got {len(found)}"
            packages_to_publish.append(found[0].name)
            logger.info(f"Package {found[0]} is built.")
        else:
            # Current python package is not changed, and it already exists in repo, reuse it.
            shutil.copy(
                final_python_package_path,
                self.packages_output_path
            )
            logger.info(f"Package {final_python_package_path.name} is reused from repo.")

        # Do the same with the 'agent-libs' package.
        final_agent_libs_package_path, final_agent_libs_version = self._get_final_package_path_and_version(
            package_name=AGENT_LIBS_PACKAGE_NAME,
            last_repo_package_file_path=last_repo_agent_libs_package_path
        )

        # The agent-libs package is not found in repo, build it.
        if final_agent_libs_package_path is None:
            package_root = self.AGENT_LIBS_BUILD_STEP.get_output_directory(work_dir=self.work_dir) / "agent_libs"

            check_call_with_log(
                [
                    *self.agent_libs_build_command_args,
                    "-v", final_agent_libs_version,
                    "-C", str(package_root),
                    "--depends", f"scalyr-agent-python3 = {final_python_version}",
                ],
                cwd=str(self.packages_output_path)
            )
            if self.PACKAGE_TYPE == "deb":
                found = list(self.packages_output_path.glob(
                    f"{AGENT_LIBS_PACKAGE_NAME}_{final_agent_libs_version}_{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
                ))
            elif self.PACKAGE_TYPE == "rpm":
                found = list(self.packages_output_path.glob(
                    f"{AGENT_LIBS_PACKAGE_NAME}-{final_agent_libs_version}-1.{self.PACKAGE_ARCHITECTURE}.{self.PACKAGE_TYPE}"
                ))
            else:
                raise Exception(f"Unknown package type {self.PACKAGE_TYPE}")

            assert len(found) == 1, f"Number of result agent_libs packages has to be 1, got {len(found)}"
            packages_to_publish.append(found[0].name)
            logger.info(f"Package {found[0].name} is built.")
        else:
            # Current agent-libs package is not changed, and it already exists in repo, reuse it.
            shutil.copy(
                final_agent_libs_package_path,
                self.packages_output_path
            )
            logger.info(f"Package {final_agent_libs_package_path.name} is reused from repo.")

        # Also write special json file which contain information about packages that have to be published.
        # We have to use it in order to skip the publishing of the packages that are reused and already in the repo.
        packages_to_publish_file = self.packages_output_path / "packages_to_publish.json"
        packages_to_publish_file.write_text(
            json.dumps(packages_to_publish)
        )

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

    def _search_for_packages_in_repo(
            self,
            params: Dict,
            token: str,
            user_name: str,
            repo_name: str,
    ) -> List:
        """

        :param params: Params for the url query.
        :param token: Packagecloud token
        :param repo_name: Target Packagecloud repo.
        :param user_name: Target Packagecloud user.
        :return: List of found packages.
        """
        import requests
        from requests.auth import HTTPBasicAuth

        auth = HTTPBasicAuth(token, "")

        param_filters = {
            "deb": "debs",
            "rpm": "rpms"
        }

        params["filter"] = param_filters[self.PACKAGE_TYPE]

        with requests.Session() as s:
            resp = s.get(
                url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
                params=params,
                auth=auth
            )

        resp.raise_for_status()

        packages = resp.json()

        # filter only packages with appropriate architecture.

        arch_packages = [p for p in packages]
        return arch_packages

    def find_last_repo_package(
            self,
            package_name: str,
            token: str,
            user_name: str,
            repo_name: str,

    ) -> Optional[str]:
        """
        Find the most recent version of the given package in the repo..
        :param package_name: Name of the package.
        :param token: Packagecloud token
        :param repo_name: Target Packagecloud repo.
        :param user_name: Target Packagecloud user.
        :return: filename of the package if found, or None.
        """

        packages = self._search_for_packages_in_repo(
            params={
                "q": f"{package_name}",
            },
            token=token,
            user_name=user_name,
            repo_name=repo_name
        )

        if len(packages) == 0:
            logger.info(f"Could not find any package with name {package_name}")
            return None

        last_package = packages[-1]

        return last_package["filename"]

    def download_package_from_repo(
            self,
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

        packages = self._search_for_packages_in_repo(
            params={
                "q": f"{package_filename}",
            },
            token=token,
            user_name=user_name,
            repo_name=repo_name
        )

        assert len(packages) == 1, f"Expected number of found packages is 1, got {len(packages)}."
        last_package = packages[-1]

        import requests
        from requests.auth import HTTPBasicAuth

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
                    # If you have chunk encoded response uncomment if
                    # and set chunk_size parameter to None.
                    # if chunk:
                    f.write(chunk)

        return package_path

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(PythonPackageBuilder, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command")

        build_packages_parser = subparsers.add_parser(
            "build", help="Build needed packages."
        )

        build_packages_parser.add_argument(
            "--last-repo-python-package-file",
            dest="last_repo_python_package_file",
            required=False,
            help="Path to the python package file. If specified, then the python "
                 "dependency package from this path will be reused instead of building a new one."
        )
        build_packages_parser.add_argument(
            "--last-repo-agent-libs-package-file",
            dest="last_repo_agent_libs_package_file",
            required=False,
            help="Path to the agent libs package file. If specified, then the agent-libs dependency package from this "
                 "path will be reused instead of building a new one."
        )

        def _add_packagecloud_args(_parser):
            _parser.add_argument(
                "--token",
                required=True,
                help="Auth token for packagecloud."
            )

            _parser.add_argument(
                "--user-name",
                dest="user_name",
                required=True,
                help="Target username for packagecloud."
            )

            _parser.add_argument(
                "--repo-name",
                dest="repo_name",
                required=True,
                help="Target repo for packagecloud."
            )

        publish_packages_parser = subparsers.add_parser(
            "publish",
            help="Publish packages that are built by 'build' command."
        )
        publish_packages_parser.add_argument(
            "--packages-dir",
            dest="packages_dir",
            required=True,
            help="Path to a directory with packages to publish."
        )
        _add_packagecloud_args(publish_packages_parser)

        find_last_repo_package_parser = subparsers.add_parser(
            "find_last_repo_package",
            help="Find existing packages in repo, in order to reuse them."
        )

        find_last_repo_package_parser.add_argument(
            "--package-name",
            dest="package_name",
            required=True,
            choices=[PYTHON_PACKAGE_NAME, AGENT_LIBS_PACKAGE_NAME],
            help="Name of the package to find."
        )
        _add_packagecloud_args(find_last_repo_package_parser)

        download_package_parser = subparsers.add_parser(
            "download_package",
            help="Download package from repo. Used by CI/CD to reuse already existing packages from repo."
        )
        download_package_parser.add_argument(
            "--package-filename",
            dest="package_filename",
            required=True,
            help="Package filename to download."
        )
        download_package_parser.add_argument(
            "--output-dir",
            dest="output_dir",
            required=True,
            help="Path where to store downloaded package."
        )
        _add_packagecloud_args(download_package_parser)

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
                last_repo_python_package_file=args.last_repo_python_package_file,
                last_repo_agent_libs_package_file=args.last_repo_agent_libs_package_file,
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
        elif args.command == "find_last_repo_package":
            last_package_filename = builder.find_last_repo_package(
                package_name=args.package_name,
                token=args.token,
                user_name=args.user_name,
                repo_name=args.repo_name,
            )
            if last_package_filename:
                print(last_package_filename)

        elif args.command == "download_package":
            last_package_path = builder.download_package_from_repo(
                package_filename=args.package_filename,
                output_dir=args.output_dir,
                token=args.token,
                user_name=args.user_name,
                repo_name=args.repo_name,
            )
            if last_package_path:
                print(last_package_path)

        else:
            logging.error(f"Unknown command {args.command}.")
            exit(1)


class DebPythonPackageBuilderX64(PythonPackageBuilder):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"
    PYTHON_BUILD_STEP = BUILD_PYTHON_GLIBC_X86_64
    AGENT_LIBS_BUILD_STEP = BUILD_AGENT_LIBS_GLIBC_X86_64


class RpmPythonPackageBuilderX64(PythonPackageBuilder):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64
    PACKAGE_ARCHITECTURE = "x86_64"
    PACKAGE_TYPE = "rpm"
    PYTHON_BUILD_STEP = BUILD_PYTHON_GLIBC_X86_64
    AGENT_LIBS_BUILD_STEP = BUILD_AGENT_LIBS_GLIBC_X86_64


ALL_MANAGED_PACKAGE_BUILDERS = {
    "deb-amd64": DebPythonPackageBuilderX64,
    "rpm-x86_64": RpmPythonPackageBuilderX64
}
