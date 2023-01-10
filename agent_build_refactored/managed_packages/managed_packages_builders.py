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
import dataclasses
import hashlib
import json
import logging
import operator
import shutil
import subprocess
import argparse
import pathlib as pl
from typing import List, Tuple, Optional, Dict, Type


from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep, RunnerMappedPath, EnvironmentRunnerStep, DockerImageSpec,GitHubActionsSettings, IN_DOCKER
from agent_build_refactored.tools.constants import SOURCE_ROOT, DockerPlatform, Architecture, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_fhs_agent_files, add_config, create_change_logs

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
    agent's requirements much more often than Python interpreter. Agent requirements are shipped in form of venv.

The structure of the mentioned packages has to guarantee that files of these packages does not interfere with
    files of local system Python interpreter. To achieve that, the dependency packages files are installed in the 
    '/opt/scalyr-agent-2-dependencies' directory.


"""

# Name of the subdirectory of dependency packages.
AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME = "scalyr-agent-2-dependencies"

# Name of the dependency package with Python interpreter.
PYTHON_PACKAGE_NAME = "scalyr-agent-python3"

# name of the dependency package with agent requirement libraries.
AGENT_LIBS_PACKAGE_NAME = "scalyr-agent-libs"

AGENT_PACKAGE_NAME = "scalyr-agent-2"


EMBEDDED_PYTHON_VERSION = "3.11.0"
EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])

PYTHON_PACKAGE_SSL_1_1_1_VERSION = "1.1.1k"
PYTHON_PACKAGE_SSL_3_VERSION = "3.0.7"


OPENSSL_VERSION_TYPE_1_1_1 = "1_1_1"
OPENSSL_VERSION_TYPE_3 = "3"

DEFAULT_OPENSSL_VERSION = OPENSSL_VERSION_TYPE_1_1_1

AGENT_LIBS_REQUIREMENTS_CONTENT = f"{REQUIREMENTS_COMMON}\n" \
                                  f"{REQUIREMENTS_COMMON_PLATFORM_DEPENDENT}"


SUPPORTED_ARCHITECTURES = [
    Architecture.X86_64,
    Architecture.ARM64,
]


class LinuxDependencyPackagesBuilder(Runner):
    """
    Builder class that is responsible for the building of the Linux agent deb and rpm packages that are managed by package
        managers such as apt and yum.
    """

    # type of the package, aka 'deb' or 'rpm'
    PACKAGE_TYPE: str

    # package architecture, for example: amd64 for deb.
    DEPENDENCY_PACKAGES_ARCHITECTURE: Architecture

    # Name of a target distribution in the packagecloud.
    PACKAGECLOUD_DISTRO: str

    # Version of a target distribution in the packagecloud.
    PACKAGECLOUD_DISTRO_VERSION: str

    @classmethod
    def get_base_environment(cls) -> EnvironmentRunnerStep:
        return PREPARE_TOOLSET_STEPS[cls.DEPENDENCY_PACKAGES_ARCHITECTURE]

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(LinuxDependencyPackagesBuilder, cls).get_all_required_steps()

        steps.extend([
            cls._get_build_package_root_step(package_name=PYTHON_PACKAGE_NAME),
            cls._get_build_package_root_step(package_name=AGENT_LIBS_PACKAGE_NAME)
        ])
        return steps

    @property
    def dependency_packages_arch(self) -> str:
        if self.PACKAGE_TYPE == "deb":
            return self.DEPENDENCY_PACKAGES_ARCHITECTURE.as_deb_package_arch
        elif self.PACKAGE_TYPE == "rpm":
            return self.DEPENDENCY_PACKAGES_ARCHITECTURE.as_rpm_package_arch
        else:
            raise ValueError(f"Unknown package type: {self.PACKAGE_TYPE}")

    @property
    def agent_package_arch(self) -> str:
        if self.PACKAGE_TYPE == "deb":
            return Architecture.UNKNOWN.as_deb_package_arch
        elif self.PACKAGE_TYPE == "rpm":
            return Architecture.UNKNOWN.as_rpm_package_arch
        else:
            raise ValueError(f"Unknown package type: {self.PACKAGE_TYPE}")

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

    def _parse_version_from_package_file_name(self, package_file_name: str):
        """
        Parse version of the package from its filename.
        """
        _, version, _, _ = self._parser_package_file_parts(
            package_file_name=package_file_name
        )
        return version

    @classmethod
    def get_python_package_build_cmd_args(cls) -> List[str]:
        """
        Returns list of arguments for the command that builds python package.
        """

        description = "Dependency package which provides Python interpreter which is used by the agent from the " \
                      "'scalyr-agent-2 package'"

        package_arch = cls.DEPENDENCY_PACKAGES_ARCHITECTURE.get_package_arch(
            package_type=cls.PACKAGE_TYPE
        )
        return [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", package_arch,
                "-t", cls.PACKAGE_TYPE,
                "-n", PYTHON_PACKAGE_NAME,
                "--license", '"Apache 2.0"',
                "--vendor", "Scalyr",
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

    @classmethod
    def get_agent_libs_build_command_args(cls) -> List[str]:
        """
        Returns list of arguments for command that build agent-libs package.
        """

        description = "Dependency package which provides Python requirement libraries which are used by the agent " \
                      "from the 'scalyr-agent-2 package'"

        package_arch = cls.DEPENDENCY_PACKAGES_ARCHITECTURE.get_package_arch(
            package_type=cls.PACKAGE_TYPE
        )

        return [
            # fmt: off
            "fpm",
            "-s", "dir",
            "-a", package_arch,
            "-t", cls.PACKAGE_TYPE,
            "-n", AGENT_LIBS_PACKAGE_NAME,
            "--config-files", "etc/scalyr-agent-2/additional-requirements.txt",
            "--license", '"Apache 2.0"',
            "--vendor", "Scalyr",
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

    def _build_agent_package(
            self,
            agent_libs_package_version: str,
    ) -> str:

        agent_package_root = self.output_path / "agent_package_root"

        build_linux_fhs_agent_files(
            output_path=agent_package_root,
            copy_agent_source=True
        )

        install_root_executable_path = agent_package_root / f"usr/share/{AGENT_PACKAGE_NAME}/bin/scalyr-agent-2-new"
        # Add agent's executable script.
        shutil.copy(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/scalyr_agent_2/scalyr-agent-2",
            install_root_executable_path,
        )

        # Also link agent executable to usr/sbin
        usr_sbin_executable = agent_package_root / "usr/sbin/scalyr-agent-2"
        usr_sbin_executable.unlink()
        usr_sbin_executable.symlink_to("../share/scalyr-agent-2/bin/scalyr-agent-2-new")

        # Add config file
        add_config(
            SOURCE_ROOT / "config",
            agent_package_root / "etc/scalyr-agent-2"
        )

        # Copy init.d folder.
        shutil.copytree(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/scalyr_agent_2/init.d",
            agent_package_root / "etc/init.d",
            dirs_exist_ok=True
        )

        # Also remove third party libraries except tcollector.
        agent_module_path = agent_package_root / "usr/share/scalyr-agent-2/py/scalyr_agent"
        third_party_libs_dir = agent_module_path / "third_party"
        shutil.rmtree(agent_module_path / "third_party_python2")
        shutil.rmtree(agent_module_path / "third_party_tls")
        shutil.rmtree(third_party_libs_dir)

        shutil.copytree(
            SOURCE_ROOT / "scalyr_agent/third_party/tcollector",
            third_party_libs_dir / "tcollector"
        )
        shutil.copy2(
            SOURCE_ROOT / "scalyr_agent/third_party/__init__.py",
            third_party_libs_dir / "__init__.py"
        )

        version = (SOURCE_ROOT / "VERSION").read_text().strip()

        scriptlets_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/scalyr_agent_2/install-scriptlets"

        description = "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics" \
                      " and log files and transmit them to Scalyr."

        changelogs_path = self.output_path / "changelogs"
        changelogs_path.mkdir()
        create_change_logs(output_dir=changelogs_path)

        subprocess.check_call(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", self.agent_package_arch,
                "-t", self.PACKAGE_TYPE,
                "-C", str(agent_package_root),
                "-n" "scalyr-agent-2",
                "-v", version,
                "--license", "Apache 2.0",
                "--vendor", "Scalyr",
                "--provides", "scalyr-agent-2",
                "--description", description,
                "--depends", "bash >= 3.2",
                "--depends", f"{AGENT_LIBS_PACKAGE_NAME} = {agent_libs_package_version}",
                "--url", "https://www.scalyr.com",
                "--deb-user", "root",
                "--deb-group", "root",
                "--rpm-user", "root",
                "--rpm-group", "root",
                "--deb-changelog", str(changelogs_path / "changelog-deb"),
                "--rpm-changelog", str(changelogs_path / "changelog-rpm"),
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
                "--verbose",
                # fmt: on
            ],
            cwd=str(self.packages_output_path)
        )
        if self.PACKAGE_TYPE == "deb":
            package_glob = f"{AGENT_PACKAGE_NAME}_{version}_{self.agent_package_arch}.{self.PACKAGE_TYPE}"
        elif self.PACKAGE_TYPE == "rpm":
            package_glob = f"{AGENT_PACKAGE_NAME}-{version}-1.{self.agent_package_arch}.{self.PACKAGE_TYPE}"
        else:
            raise Exception(f"Unknown package type {self.PACKAGE_TYPE}")

        found = list(self.packages_output_path.glob(package_glob))
        assert len(found) == 1, f"Number of result agent packages has to be 1, got {len(found)}"
        return found[0].name


    @classmethod
    def _get_build_package_root_step(cls, package_name: str) -> ArtifactRunnerStep:

        package_to_steps = {
            PYTHON_PACKAGE_NAME: BUILD_PYTHON_PACKAGE_ROOT_STEPS,
            AGENT_LIBS_PACKAGE_NAME: BUILD_AGENT_LIBS_PACKAGE_ROOT_STEPS
        }
        steps = package_to_steps[package_name]

        return steps[cls.DEPENDENCY_PACKAGES_ARCHITECTURE]


    @classmethod
    def get_package_checksum(
            cls,
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

        build_root_step = cls._get_build_package_root_step(
            package_name=package_name
        )

        if package_name == PYTHON_PACKAGE_NAME:
            build_command_args = cls.get_python_package_build_cmd_args()
        else:
            build_command_args = cls.get_agent_libs_build_command_args()

        # Add checksum of the step that builds package files.
        sha256 = hashlib.sha256()
        sha256.update(build_root_step.checksum.encode())

        # Add arguments that are used to build package.
        for arg in build_command_args:
            sha256.update(arg.encode())

        return sha256.hexdigest()

    def build(self, stable_versions_file: str = None):
        """
        Build agent package and its dependency packages.
        # TODO this param for now is always None, this should be chaged after the first stable release.
        :param stable_versions_file: Path to JSON file with stable versions to reuse.
        """

        self.run_required()

        # Run inside the docker if needed.
        if self.runs_in_docker:
            command_args = ["build"]
            self.run_in_docker(command_args=command_args)
            return

        self.packages_output_path.mkdir(parents=True)

        # Build agent libs package
        agent_libs_version, should_build_agent_libs = _get_dependency_package_version_to_use(
            checksum=_ALL_AGENT_LIBS_PACKAGES_CHECKSUM,
            package_name=AGENT_LIBS_PACKAGE_NAME,
            stable_versions_file_path=stable_versions_file
        )

        if should_build_agent_libs:
            # build python package
            python_version, should_build_python = _get_dependency_package_version_to_use(
                checksum=_ALL_PYTHON_PACKAGES_CHECKSUM,
                package_name=PYTHON_PACKAGE_NAME,
                stable_versions_file_path=stable_versions_file,
            )
            if should_build_python:
                build_python_package_root_step = self._get_build_package_root_step(
                    package_name=PYTHON_PACKAGE_NAME
                )
                build_python_step_output = build_python_package_root_step.get_output_directory(
                    work_dir=self.work_dir
                )

                scriptlets_dir = build_python_step_output / "scriptlets"
                check_call_with_log(
                    [
                        *self.get_python_package_build_cmd_args(),
                        "-v", python_version,
                        "-C", str(build_python_step_output / "root"),
                        "--config-files", f"/opt/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/etc/preferred_openssl",
                        "--after-install", str(scriptlets_dir / "postinstall.sh"),
                        "--before-remove", str(scriptlets_dir / "preuninstall.sh"),
                        "--verbose"
                    ],
                    cwd=str(self.packages_output_path),
                )

            build_agent_libs_package_root_step = self._get_build_package_root_step(
                package_name=AGENT_LIBS_PACKAGE_NAME
            )
            build_agent_libs_step_output = build_agent_libs_package_root_step.get_output_directory(
                work_dir=self.work_dir
            )

            scriptlets_dir = build_agent_libs_step_output / "scriptlets"

            check_call_with_log(
                [
                    *self.get_agent_libs_build_command_args(),
                    "--depends", f"{PYTHON_PACKAGE_NAME} = {python_version}",
                    "--config-files", f"/opt/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/etc/additional-requirements.txt",
                    "--after-install", str(scriptlets_dir / "postinstall.sh"),
                    "-v", agent_libs_version,
                    "-C", str(build_agent_libs_step_output / "root"),
                    "--verbose"
                ],
                cwd=str(self.packages_output_path),
            )

        self._build_agent_package(
            agent_libs_package_version=agent_libs_version,
        )

    def _get_final_package_path_and_version(
            self,
            package_name: str,
            last_repo_package_file_path: pl.Path = None,
    ) -> Tuple[Optional[pl.Path], str]:
        """
        Get path and version of the final package to build.
        :param package_name: name of the package.
        :param last_repo_package_file_path: Path to a last package from the repo. If specified and there are no changes
            between current package and package from repo, then package from repo is used instead of building a new one.
        :return: Tuple with:
            - Path to the final package. None if package is not found in repo.
            - Version of the final package.
        """
        final_package_path = None

        current_package_checksum = self.get_package_checksum(
            package_name=package_name
        )

        if last_repo_package_file_path is None:
            # If there is no any recent version of the package in repo then build new version for the first package.
            final_package_version = f"1+{current_package_checksum}"
        else:
            # If there is a recent version of the package in the repo, then parse its checksum and compare it
            # with the checksum of the current package. If checksums are identical, then we can reuse
            # package version from the repo.
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
                    *self.get_python_package_build_cmd_args,
                    "-v", final_python_version,
                    "-C", str(package_root),
                    "--verbose"
                ],
                cwd=str(self.packages_output_path)
            )
            if self.PACKAGE_TYPE == "deb":
                found = list(self.packages_output_path.glob(
                    f"{PYTHON_PACKAGE_NAME}_{final_python_version}_{self.dependency_packages_arch}.{self.PACKAGE_TYPE}"
                ))
            elif self.PACKAGE_TYPE == "rpm":
                found = list(self.packages_output_path.glob(
                    f"{PYTHON_PACKAGE_NAME}-{final_python_version}-1.{self.dependency_packages_arch}.{self.PACKAGE_TYPE}"
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

        # Do the same and build the 'agent-libs' package.
        final_agent_libs_package_path, final_agent_libs_version = self._get_final_package_path_and_version(
            package_name=AGENT_LIBS_PACKAGE_NAME,
            last_repo_package_file_path=last_repo_agent_libs_package_path
        )

        # The agent-libs package is not found in repo, build it.
        if final_agent_libs_package_path is None:
            package_root = self.AGENT_LIBS_BUILD_STEP.get_output_directory(work_dir=self.work_dir) / "agent_libs"

            check_call_with_log(
                [
                    *self.get_agent_libs_build_command_args,
                    "-v", final_agent_libs_version,
                    "-C", str(package_root),
                    "--depends", f"scalyr-agent-python3 = {final_python_version}",
                    "--verbose"
                ],
                cwd=str(self.packages_output_path)
            )
            if self.PACKAGE_TYPE == "deb":
                found = list(self.packages_output_path.glob(
                    f"{AGENT_LIBS_PACKAGE_NAME}_{final_agent_libs_version}_{self.dependency_packages_arch}.{self.PACKAGE_TYPE}"
                ))
            elif self.PACKAGE_TYPE == "rpm":
                found = list(self.packages_output_path.glob(
                    f"{AGENT_LIBS_PACKAGE_NAME}-{final_agent_libs_version}-1.{self.dependency_packages_arch}.{self.PACKAGE_TYPE}"
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

        # Build agent_package
        agent_package_path = self._build_agent_package(
            agent_libs_package_version=final_agent_libs_version
        )
        packages_to_publish.append(str(agent_package_path))

        # Also write special json file which contain information about packages that have to be published.
        # We have to use it in order to skip the publishing of the packages that are reused and already in the repo.
        packages_to_publish_file = self.packages_output_path / "packages_to_publish.json"
        packages_to_publish_file.write_text(
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

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(LinuxDependencyPackagesBuilder, cls).add_command_line_arguments(parser=parser)

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
        super(LinuxDependencyPackagesBuilder, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "build":
            builder.build()
            if not IN_DOCKER:
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


# Version of the  Python build dependencies.
_PYTHON_BUILD_DEPENDENCIES_VERSIONS = {
    "XZ_VERSION": "5.2.6",
    "OPENSSL_1_1_1_VERSION": PYTHON_PACKAGE_SSL_1_1_1_VERSION,
    "OPENSSL_3_VERSION": PYTHON_PACKAGE_SSL_3_VERSION,
    "LIBFFI_VERSION": "3.4.2",
    "UTIL_LINUX_VERSION": "2.38",
    "NCURSES_VERSION": "6.3",
    "LIBEDIT_VERSION": "20210910-3.1",
    "GDBM_VERSION": "1.23",
    "ZLIB_VERSION": "1.2.13",
    "BZIP_VERSION": "1.0.8",
}

# Step that downloads all Python dependencies.
DOWNLOAD_PYTHON_DEPENDENCIES = ArtifactRunnerStep(
        name="download_build_dependencies",
        script_path="agent_build_refactored/managed_packages/steps/download_build_dependencies/download_build_dependencies.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/steps/download_build_dependencies/gnu-keyring.gpg",
            "agent_build_refactored/managed_packages/steps/download_build_dependencies/gpgkey-5C1D1AA44BE649DE760A.gpg",
        ],
        base=DockerImageSpec(
            name="ubuntu:22.04",
            platform=DockerPlatform.AMD64.value
        ),
        environment_variables={
            **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
        }

    )


def create_build_openssl_steps(
        openssl_version_type: str
) -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Create steps that build openssl library with given version.
    :param openssl_version_type: type of the OpenSSL, eg. 1_1_1, or 3
    :return:
    """
    steps = {}

    if openssl_version_type == OPENSSL_VERSION_TYPE_3:
        script_name = "build_openssl_3.sh"
        openssl_version = PYTHON_PACKAGE_SSL_3_VERSION
    else:
        script_name = "build_openssl_1_1_1.sh"
        openssl_version = PYTHON_PACKAGE_SSL_1_1_1_VERSION

    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        step = ArtifactRunnerStep(
            name=f"build_openssl_{openssl_version_type}_{architecture.value}",
            script_path=f"agent_build_refactored/managed_packages/steps/build_openssl/{script_name}",
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            required_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES,
            },
            environment_variables={
                "OPENSSL_VERSION": openssl_version,
            },
            github_actions_settings=GitHubActionsSettings(
                run_in_remote_docker=run_in_remote_docker
            )
        )
        steps[architecture] = step

    return steps


def create_install_build_environment_steps() -> Dict[Architecture, EnvironmentRunnerStep]:
    """
    Create steps that create build environment with gcc and other tools for python compilation.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        build_env_info = _SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS[architecture]

        step = EnvironmentRunnerStep(
            name=f"install_build_environment_{architecture.value}",
            script_path=f"agent_build_refactored/managed_packages/steps/install_build_environment/{build_env_info.script_name}",
            base=DockerImageSpec(
                name=build_env_info.image,
                platform=architecture.as_docker_platform.value
            ),
            github_actions_settings=GitHubActionsSettings(
                run_in_remote_docker=run_in_remote_docker,
                cacheable=True,
            )
        )
        steps[architecture] = step

    return steps


def create_build_python_dependencies_steps(
) -> Dict[Architecture, ArtifactRunnerStep]:
    """
    This function creates step that builds Python dependencies.
    """

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        step = ArtifactRunnerStep(
            name=f"build_python_dependencies_{architecture.value}",
            script_path="agent_build_refactored/managed_packages/steps/build_python_dependencies.sh",
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            required_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES
            },
            environment_variables={
                **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
            },
            github_actions_settings=GitHubActionsSettings(
                run_in_remote_docker=run_in_remote_docker
            )
        )
        steps[architecture] = step

    return steps


def create_build_python_steps(
        openssl_version_type: str
) -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Function that creates step instances that build Python interpreter.
    :return: Result steps mapped to architectures..
    """

    install_prefix = f"/opt/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}"

    steps = {}

    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        build_python = ArtifactRunnerStep(
            name=f"build_python_{openssl_version_type}_{architecture.value}",
            script_path="agent_build_refactored/managed_packages/steps/build_python.sh",
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            required_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES,
                "BUILD_PYTHON_DEPENDENCIES": BUILD_PYTHON_DEPENDENCIES_STEPS[architecture],
                "BUILD_OPENSSL": BUILD_OPENSSL_STEPS[openssl_version_type][architecture],
            },
            environment_variables={
                "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
                "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
                "INSTALL_PREFIX": install_prefix,

            },
            github_actions_settings=GitHubActionsSettings(
                run_in_remote_docker=run_in_remote_docker
            )
        )

        steps[architecture] = build_python

    return steps


# Simple dataclass to store information about base environment step.
@dataclasses.dataclass
class BuildEnvInfo:
    # Script to run.
    script_name: str
    # Docker image to use.
    image: str


BUILD_ENV_CENTOS_6 = BuildEnvInfo(
        script_name="install_gcc_centos_6.sh",
        image="centos:6"
    )
BUILD_ENV_CENTOS_7 = BuildEnvInfo(
        script_name="install_gcc_centos_7.sh",
        image="centos:7"
    )


_SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS = {
    Architecture.X86_64: BUILD_ENV_CENTOS_6,
    Architecture.ARM64: BUILD_ENV_CENTOS_7,
}


def create_build_python_package_root_steps() -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Function that creates step instances that build Python interpreter.
    :return: Result steps dict mapped to architectures.
    """
    steps = {}

    for architecture in SUPPORTED_ARCHITECTURES:
        build_env_info = _SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS[architecture]
        if "ubuntu" in build_env_info.image:
            libssl_dir = "/usr/local/lib"
        else:
            libssl_dir = "/usr/local/lib64"

        step = ArtifactRunnerStep(
            name="build_python_package_root",
            script_path="agent_build_refactored/managed_packages/steps/build_python_package_root.sh",
            tracked_files_globs=[
                "agent_build_refactored/managed_packages/scalyr_agent_python3/agent-python3-config",
                "agent_build_refactored/managed_packages/scalyr_agent_python3/install-scriptlets/postinstall.sh",
                "agent_build_refactored/managed_packages/scalyr_agent_python3/install-scriptlets/preuninstall.sh"
            ],
            base=PREPARE_TOOLSET_STEPS[architecture],
            required_steps={
                "BUILD_OPENSSL_1_1_1": BUILD_OPENSSL_STEPS[OPENSSL_VERSION_TYPE_1_1_1][architecture],
                "BUILD_OPENSSL_3": BUILD_OPENSSL_STEPS[OPENSSL_VERSION_TYPE_3][architecture],
                "BUILD_PYTHON_WITH_OPENSSL_1_1_1": BUILD_PYTHON_STEPS[OPENSSL_VERSION_TYPE_1_1_1][architecture],
                "BUILD_PYTHON_WITH_OPENSSL_3": BUILD_PYTHON_STEPS[OPENSSL_VERSION_TYPE_3][architecture],


            },
            environment_variables={
                "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
                "INSTALL_PREFIX": "/opt/scalyr-agent-2-dependencies",
                "LIBSSL_DIR": libssl_dir
            },

        )

        steps[architecture] = step

    return steps


def create_build_dev_requirements_steps() -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Create steps that build all agent project requirements.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        build_dev_requirements_step = ArtifactRunnerStep(
            name=f"build_dev_requirements_{architecture.value}",
            script_path="agent_build_refactored/managed_packages/steps/build_dev_requirements.sh",
            tracked_files_globs=[
                "dev-requirements-new.txt",
            ],
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            required_steps={
                "BUILD_PYTHON_DEPENDENCIES": BUILD_PYTHON_DEPENDENCIES_STEPS[architecture],
                "BUILD_OPENSSL": BUILD_OPENSSL_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
                "BUILD_PYTHON": BUILD_PYTHON_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
            },
            environment_variables={
                "RUST_VERSION": "1.63.0",
                "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
                run_in_remote_docker=run_in_remote_docker
            )
        )
        steps[architecture] = build_dev_requirements_step

    return steps


def create_build_agent_libs_venv_steps() -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Function that creates steps that install agent requirement libraries.
    :return: Result steps dict mapped to architectures..
    """

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:

        run_in_remote_docker = architecture != Architecture.X86_64

        build_agent_libs_step = ArtifactRunnerStep(
            name=f"build_agent_libs_venv_{architecture.value}",
            script_path="agent_build_refactored/managed_packages/steps/build_agent_libs_venv.sh",
            tracked_files_globs=[
                "dev-requirements-new.txt",
            ],
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            required_steps={
                "BUILD_OPENSSL": BUILD_OPENSSL_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
                "BUILD_PYTHON": BUILD_PYTHON_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
                "BUILD_DEV_REQUIREMENTS": BUILD_DEV_REQUIREMENTS_STEPS[architecture]
            },
            environment_variables={
                "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
                "REQUIREMENTS": AGENT_LIBS_REQUIREMENTS_CONTENT
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
                run_in_remote_docker=run_in_remote_docker
            )
        )
        steps[architecture] = build_agent_libs_step

    return steps


def create_build_agent_libs_package_root_steps() -> Dict[Architecture, ArtifactRunnerStep]:
    """
    Function that creates steps that builds agent requirement libraries package roots.
    :return: Result steps dict mapped to architectures.
    """

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:

        step = ArtifactRunnerStep(
            name="build_agent_libs_package_root",
            script_path="agent_build_refactored/managed_packages/steps/build_agent_libs_package_root.sh",
            tracked_files_globs=[
                "agent_build_refactored/managed_packages/scalyr_agent_libs/additional-requirements.txt",
                "agent_build_refactored/managed_packages/scalyr_agent_libs/agent-libs-config",
                "agent_build_refactored/managed_packages/scalyr_agent_libs/install-scriptlets/postinstall.sh",
            ],
            base=PREPARE_TOOLSET_STEPS[architecture],
            required_steps={
                "BUILD_AGENT_LIBS": BUILD_AGENT_LIBS_VENV_STEPS[architecture],
            },
            environment_variables={
                "REQUIREMENTS": AGENT_LIBS_REQUIREMENTS_CONTENT
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
            )

        )
        steps[architecture] = step

    return steps


# Steps that prepares build environment.
INSTALL_BUILD_ENVIRONMENT_STEPS = create_install_build_environment_steps()

# Steps that build Python dependencies.
BUILD_PYTHON_DEPENDENCIES_STEPS = create_build_python_dependencies_steps()

# Steps that build OpenSSL Python dependency, 1.1.1 and 3 versions.
BUILD_OPENSSL_STEPS = {
    OPENSSL_VERSION_TYPE_1_1_1: create_build_openssl_steps(openssl_version_type=OPENSSL_VERSION_TYPE_1_1_1),
    OPENSSL_VERSION_TYPE_3: create_build_openssl_steps(openssl_version_type=OPENSSL_VERSION_TYPE_3),
}

# Create steps that build Python interpreter with OpenSSl 1.1.1 and 3
BUILD_PYTHON_STEPS = {
    OPENSSL_VERSION_TYPE_1_1_1: create_build_python_steps(openssl_version_type=OPENSSL_VERSION_TYPE_1_1_1),
    OPENSSL_VERSION_TYPE_3: create_build_python_steps(openssl_version_type=OPENSSL_VERSION_TYPE_3),
}

# Create steps that build and install all agent dev requirements.
BUILD_DEV_REQUIREMENTS_STEPS = create_build_dev_requirements_steps()

# Create steps that build agent requirement libs inside venv.
BUILD_AGENT_LIBS_VENV_STEPS = create_build_agent_libs_venv_steps()


def create_prepare_toolset_steps() -> Dict[Architecture, EnvironmentRunnerStep]:
    """
    Create steps that prepare environment with all needed tools.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        base_image = DockerImageSpec(
            name="ubuntu:22.04",
            platform=architecture.as_docker_platform.value
        )

        prepare_toolset_step = EnvironmentRunnerStep(
            name=f"prepare_toolset_{architecture.value}",
            script_path="agent_build_refactored/managed_packages/steps/prepare_toolset.sh",
            base=base_image,
            required_steps={
                "BUILD_OPENSSL": BUILD_OPENSSL_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
                "BUILD_PYTHON": BUILD_PYTHON_STEPS[DEFAULT_OPENSSL_VERSION][architecture],
                "BUILD_DEV_REQUIREMENTS": BUILD_DEV_REQUIREMENTS_STEPS[architecture],
            },
            environment_variables={
                "SUBDIR_NAME": AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
                "FPM_VERSION": "1.14.2",
                "PACKAGECLOUD_VERSION": "0.3.11",
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
                pre_build_in_separate_job=True,
            )
        )

        steps[architecture] = prepare_toolset_step

    return steps


PREPARE_TOOLSET_STEPS = create_prepare_toolset_steps()

# Create steps that build root of the dependency Package which provides Python interpreter for the Agent.
BUILD_PYTHON_PACKAGE_ROOT_STEPS = create_build_python_package_root_steps()

# Create steps that build root of the dependency Package which provides requirement Python libraries for the Agent.
BUILD_AGENT_LIBS_PACKAGE_ROOT_STEPS = create_build_agent_libs_package_root_steps()


ALL_MANAGED_PACKAGE_BUILDERS: Dict[str, Type[LinuxDependencyPackagesBuilder]] = {}

# Iterate through all supported architectures and create package builders classes for each.
for arch in SUPPORTED_ARCHITECTURES:
    class DebLinuxDependencyPackagesBuilder(LinuxDependencyPackagesBuilder):
        PACKAGE_TYPE = "deb"
        PACKAGECLOUD_DISTRO = "any"
        PACKAGECLOUD_DISTRO_VERSION = "any"
        DEPENDENCY_PACKAGES_ARCHITECTURE = arch


    class RpmLinuxDependencyPackagesBuilder(LinuxDependencyPackagesBuilder):
        PACKAGE_TYPE = "rpm"
        PACKAGECLOUD_DISTRO = "rpm_any"
        PACKAGECLOUD_DISTRO_VERSION = "rpm_any"
        DEPENDENCY_PACKAGES_ARCHITECTURE = arch

    # Since we create builders "dynamically" we should assign name to each of them, so
    # they can be accessible later.
    for cls in [DebLinuxDependencyPackagesBuilder, RpmLinuxDependencyPackagesBuilder]:
        cls.assign_fully_qualified_name(
            class_name=cls.__name__,
            module_name=__name__,
            class_name_suffix=arch.value
        )
        name = f"{cls.PACKAGE_TYPE}-{arch.value}"
        ALL_MANAGED_PACKAGE_BUILDERS[name] = cls


def _calculate_all_packages_checksum(package_name: str):
    """
    Calculate checksum for ALL packages with given name.
    """
    sha256 = hashlib.sha256()
    for builder_name in sorted(ALL_MANAGED_PACKAGE_BUILDERS.keys()):
        builder_cls = ALL_MANAGED_PACKAGE_BUILDERS[builder_name]
        checksum = builder_cls.get_package_checksum(package_name=package_name)
        sha256.update(checksum.encode())

    return sha256.hexdigest()


# We calculate checksum of packages for all architectures, so they can have common version.
_ALL_PYTHON_PACKAGES_CHECKSUM = _calculate_all_packages_checksum(package_name=PYTHON_PACKAGE_NAME)

# The same with agent libs package.
_ALL_AGENT_LIBS_PACKAGES_CHECKSUM = _calculate_all_packages_checksum(package_name=AGENT_LIBS_PACKAGE_NAME)


def _get_dependency_package_version_to_use(
        checksum: str,
        package_name: str,
        stable_versions_file_path: str = None
) -> Tuple[str, bool]:
    """
    This function determines if package with given name has been changed or not.
    :param checksum: checksum of package's all architectures.
    :param package_name: name of package to check.
    :param stable_versions_file_path: If None path to JSON file with stable package version that may be reused.
    :return Tuple where first element is a version, and second boolean flag that indicates whether package should be
        rebuilt or not.
    """
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
