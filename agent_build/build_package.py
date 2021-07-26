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

import pathlib as pl
import tarfile
import abc
import argparse
import platform
import shutil
import subprocess
import time
import sys
import stat
import hashlib
import uuid
import io
from typing import Union, Optional

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

sys.path.append(str(__SOURCE_ROOT__))

from agent_build.common import cat_files, recursively_delete_files_by_name

from agent_build import common

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"

class PackageBuilder(abc.ABC):
    """
    The base abstraction for all Scalyr Agent package builders.
    It provides the set of, lets say, "actions" which correspond to the command line arguments of this script:
        1. 'build' - Build the actual package.
        2. 'prepare-build-environment' - Prepare the build environment. This action is not used during the build, but it
            prepares the current system to be able to run the build action, for example, by installing tools which are
            required during the build. First of all, this action should be useful on CI/CD platforms such as Github
            Actions, where the runner starts in a clean virtual environment every time, so it is good to have a
            consistent way install all things which are needed for the build.
                One problem, which is also connected with CI/CD, is that the preparation of the build environment can be
            very time consuming (for example - downloading or compiling needed tool). The common practice in such cases
            is to use CI/CD caching mechanisms to cache the intermediate results and reuse them later. In order to take
            advantage from such mechanisms, this action also provides ability to specify the path to the cache and to
            save/reuse intermediate results.

        3. 'dump-checksum' - Dump the checksum of files which are used during the previous
                action.
            Explanation: As it has been said, the second action can cache its intermediate results. But to guarantee
            the integrity of the cache, there has to be a key which corresponds to the current content of the files
            which are used in the second action. If content of used files is changed, then key is also changed and
            cache has to be invalidated, very common Ci/CD logic.
                This action calculates the SHA256 of all files which are used during the second action and dumps it
            into the file which can be used by CI/CD caching mechanism.

    Package builder can be also configured to run its own copy in the docker instead of building directly on the system
    where the code runs. It may be very useful, because there is no need to prepare the current system to be able to
    perform the build. That also provides more consistent build results, no mater what is the host system.
    """

    # Path to the script which has to be executed to prepare the build environment (aka action 2) and install all tools
    # and programs which are required by this package builder.
    PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH: Union[str, pl.Path] = None

    # The list of files which are somehow used during the preparation of the build environment. This is needed to
    # calculate their checksum. (see action 3)
    FILES_USED_IN_BUILD_ENVIRONMENT: Union[str, pl.Path] = []

    # If this flag True, then the builder will run inside the docker.
    DOCKERIZED = False

    # Name of the image in case if build is performed inside the docker. Has to pe specified if 'DOCKERIZED' is True.
    BASE_DOCKER_IMAGE = None

    # The name of the package type
    PACKAGE_TYPE = None

    # The type of the installation. For more info, see the 'InstallType' in the scalyr_agent/__scalyr__.py
    INSTALL_TYPE = None

    def __init__(
            self,
            variant: str = None,
            no_versioned_file_name: bool = False,
    ):
        """
        :param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
        :param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.
        """
        # The path where the build output will be stored.
        self._build_output_path: Optional[pl.Path] = None

        # The path of the folder where all files of the package will be stored.
        # May be help full for the debug purposes.
        self._package_files_path: Optional[pl.Path] = None

        self._variant = variant
        self._no_versioned_file_name = no_versioned_file_name

    def build(
            self,
            output_path: Union[str, pl.Path],
            locally: bool = False
    ):
        """
        The function where the actual build of the package happens.
        :param output_path: Path to the directory where the resulting output has to be stored.
        :param locally: If True, the build occurs directly on the system where this code is running, if False,
            the build will be done inside the docker.
        """
        output_path = pl.Path(output_path).absolute()

        if output_path.exists():
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)
        self._build_output_path = pl.Path(output_path) / type(self).PACKAGE_TYPE
        self._package_files_path = self._build_output_path / "package_root"

        # If locally option is specified or builder class is not dockerized by default then just build the package
        # directly on this system.
        if locally or not type(self).DOCKERIZED:
            self._build(
                output_path=output_path
            )

        # The package has to be build inside the docker.
        else:
            # Make sure that the base image with build environment is build.
            self.prepare_build_environment(
                locally=locally
            )

            dockerfile_path = __PARENT_DIR__ / 'Dockerfile'

            # Make changes to the existing command line arguments to pass them to the docker builder.
            command_argv = sys.argv[:]

            # Create the path for the current script file which will be used inside the docker.
            build_package_script_path = pl.Path(command_argv[0]).absolute()

            container_builder_module_path = pl.Path(
                "/scalyr-agent-2",
                pl.Path(build_package_script_path).relative_to(__SOURCE_ROOT__)
            )

            # Replace the 'host-specific' path of this script with 'docker-specific' path
            command_argv[0] = str(container_builder_module_path)

            # Since the builder can be configured to run inside the docker by default, then we have to tell it to not to
            # do so when it is already inside the docker.
            command_argv.insert(1, "--locally")

            # Also change the 'host-specific' output path.
            output_dir_index = command_argv.index("--output-dir")
            command_argv[output_dir_index + 1] = "/tmp/build"

            # Join everything into one command string.
            command = common.shlex_join(command_argv)

            image_name = f"scalyr-agent-{type(self).PACKAGE_TYPE}-builder".lower()

            # Run the image build. The package also has to be build during that.
            # Building the package during the image build is more convenient than building it in the container
            # because the the docker build caching mechanism will save out time when nothing in agent source is changed.
            # This can save time during the local debugging.

            subprocess.check_call(
                [
                    "docker", "build", "-t", image_name,
                    "--build-arg", f"BASE_IMAGE_NAME={self._get_build_environment_docker_image_name()}",
                    "--build-arg", f'BUILD_COMMAND=python3 {command}',
                    "-f", str(dockerfile_path),
                    str(__SOURCE_ROOT__)
                ]
            )

            # The image is build and package has to be fetched from it, so create the container...

            # Remove the container wth the same name if exists.
            container_name = image_name
            subprocess.check_call(
                ["docker", "rm", "-f", container_name]
            )

            # Create the container.
            subprocess.check_call(
                ["docker", "create", "--name", container_name, image_name ]
            )

            # Copy package output from the container.
            subprocess.check_call(
                ["docker", "cp", "-a", f"{container_name}:/tmp/build/.", str(output_path)],
            )

            # Remove the container.
            subprocess.check_call(
                ["docker", "rm", "-f", container_name]
            )

    @classmethod
    def prepare_build_environment(
            cls,
            cache_dir: Union[str, pl.Path] = None,
            locally: bool = False
    ):
        """
        Prepare the build environment. For more info see 'prepare-build-environment' action in class docstring.
        """

        if locally or not cls.DOCKERIZED:
            # Prepare the build environment on the current system.

            # Choose the shell according to the operation system.
            if platform.system() == "Windows":
                shell = "powershell"
            else:
                shell = "bash"

            command = [shell, str(cls.PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH)]

            # If cache directory is presented, then we pass it as an additional argument to the
            # 'prepare build environment' script, so it can use the cache too.
            if cache_dir:
                command.append(str(pl.Path(cache_dir)))

            # Run the 'prepare build environment' script in previously chosen shell.
            subprocess.check_call(
                command,
            )
        else:
            # Instead of preparing the build environment on the current system, create the docker image and prepare the
            # build environment there. If cache directory is specified, then the docker image will be serialized to the
            # file and that file will be stored in the cache.

            # Get the name of the builder image.
            image_name = cls._get_build_environment_docker_image_name()

            # Before the build, check if there is already an image with the same name. The name contains the checksum
            # of all files which are used in it, so the name identity also guarantees the content identity.
            output = subprocess.check_output(
                ["docker", "images", "-q", image_name]
            ).decode().strip()

            if output:
                # The image already exists, skip the build.
                print(f"Image '{image_name}' already exists, skip the build and reuse it.")
                return

            save_to_cache = False

            # If cache directory is specified, then check if the image file is already there and we can reuse it.
            if cache_dir:
                cache_dir = pl.Path(cache_dir)
                cached_image_path = cache_dir / image_name
                if cached_image_path.is_file():
                    print("Cached image file has been found, loading and reusing it instead of building.")
                    subprocess.check_call(
                        ["docker", "load", "-i", str(cached_image_path)]
                    )
                    return
                else:
                    # Cache is used but there is no suitable image file. Set the flag to signal that the built
                    # image has to be save to the cache.
                    save_to_cache = True

            print(f"Build image '{image_name}'")

            # Create the builder image.
            # Instead of using the 'docker build', just create the image from 'docker commit' from the container.

            container_root_path = pl.Path("/scalyr-agent-2")

            # All files, which are used in the build have to be mapped to the docker container.
            volumes_mappings = []
            for used_path in cls._get_files_used_in_build_environment():
                rel_used_path = pl.Path(used_path).relative_to(__SOURCE_ROOT__)
                abs_host_path = __SOURCE_ROOT__ / rel_used_path
                abs_container_path = container_root_path / rel_used_path
                volumes_mappings.extend(["-v", f"{abs_host_path}:{abs_container_path}"])

            # Map the prepare environment script's path to the docker.
            container_prepare_env_script_path = pl.Path(
                container_root_path,
                pl.Path(cls.PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH).relative_to(__SOURCE_ROOT__)
            )

            container_name = cls.__name__

            # Remove if such container exists.
            subprocess.check_call(
                ["docker", "rm", "-f", container_name]
            )

            # Create container and run the 'prepare environment' script in it.
            subprocess.check_call(
                [
                    "docker", "run", "-i", "--name", container_name,
                    *volumes_mappings,
                    cls.BASE_DOCKER_IMAGE,
                    str(container_prepare_env_script_path)]
            )

            # Save the current state of the container into image.
            subprocess.check_call(
                ["docker", "commit", container_name, image_name]
            )

            # Save image if caching is enabled.
            if cache_dir and save_to_cache:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached_image_path = cache_dir / image_name
                print(f"Saving '{image_name}' image file into cache.")
                with cached_image_path.open("wb") as f:
                    subprocess.check_call(
                        ["docker", "save", image_name],
                        stdout=f

                    )

    @classmethod
    def dump_build_environment_files_content_checksum(
            cls,
            checksum_output_path: Union[str, pl.Path]
    ):
        """
        Dump the checksum of the content of the file used during the 'prepare-build-environment' action.
            For more info see 'dump-checksum' action in class docstring.

        :param checksum_output_path: Is mainly created for the CI/CD purposes. If specified, the function dumps the
            file with the checksum of all the content of all files which are used during the preparation
            of the build environment. This checksum can be used by CI/CD as the cache key..
        """
        checksum = cls._get_build_environment_files_checksum()

        checksum_output_path = pl.Path(checksum_output_path)
        checksum_output_path.parent.mkdir(exist_ok=True, parents=True)
        checksum_output_path.write_text(checksum)


    @property
    def _build_info(self) -> Optional[str]:
        """Returns a string containing the package build info."""

        build_info_buffer = io.StringIO()

        # We need to execute the git command in the source root.
        # Add in the e-mail address of the user building it.
        try:
            packager_email = subprocess.check_output(
                "git config user.email", shell=True, cwd=str(__SOURCE_ROOT__)
            ).decode().strip()
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

        # Determine the last commit from the log.
        commit_id = subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
                shell=True,
                cwd=__SOURCE_ROOT__,
        ).decode().strip()

        print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

        # Include the branch just for safety sake.
        branch = subprocess.check_output(
            "git branch | cut -d ' ' -f 2", shell=True, cwd=__SOURCE_ROOT__
        ).decode().strip()
        print("From branch: %s" % branch.strip(), file=build_info_buffer)

        # Add a timestamp.
        print(
            "Build time: %s" % str(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
            file=build_info_buffer,
        )

        return build_info_buffer.getvalue()

    @staticmethod
    def _add_config(
            config_source_path: Union[str, pl.Path], output_path: Union[str, pl.Path]
    ):
        """
        Copy config folder from the specified path to the target path.
        """
        config_source_path = pl.Path(config_source_path)
        output_path = pl.Path(output_path)
        # Copy config
        shutil.copytree(config_source_path, output_path)

        # Make sure there is an agent.d directory regardless of the config directory we used.
        agent_d_path = output_path / "agent.d"
        agent_d_path.mkdir(exist_ok=True)
        # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
        # readable by others.
        agent_d_path.chmod(int("741", 8))

    @staticmethod
    def _add_certs(
            path: Union[str, pl.Path],
            intermediate_certs=True,
            copy_other_certs=True
    ):
        """
        Create needed certificates files in the specified path.
        """

        path = pl.Path(path)
        path.mkdir(parents=True)
        source_certs_path = __SOURCE_ROOT__ / "certs"

        cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

        if intermediate_certs:
            cat_files(
                source_certs_path.glob("*_intermediate.pem"),
                path / "intermediate_certs.pem",
            )
        if copy_other_certs:
            for cert_file in source_certs_path.glob("*.pem"):
                shutil.copy(cert_file, path / cert_file.name)

    @property
    def _package_version(self) -> str:
        """The version of the agent"""
        return pl.Path(__SOURCE_ROOT__, "VERSION").read_text().strip()

    @classmethod
    def _get_files_used_in_build_environment(cls):
        """
        Get the list of all files which are used in the 'prepare-build-environment action.

        """

        def get_dir_files(dir_path: pl.Path):
            # ignore those directories.
            if dir_path.name == "__pycache__":
                return []

            result = []
            for child_path in dir_path.iterdir():
                if child_path.is_dir():
                    result.extend(get_dir_files(child_path))
                else:
                    result.append(child_path)

            return result

        used_files = []

        # The build environment praperetion script is also has to be included.
        used_files.append(cls.PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH)

        # Since the 'FILES_USED_IN_BUILD_ENVIRONMENT' class attribute can also contain directories, look for them and
        # include all files inside them recursively.
        for path in cls.FILES_USED_IN_BUILD_ENVIRONMENT:
            path = pl.Path(path)
            if path.is_dir():
                used_files.extend(get_dir_files(path))
            else:
                used_files.append(path)

        return used_files

    @classmethod
    def _get_build_environment_files_checksum(cls):
        """
        Calculate the sha256 checksum of all files which are used in the "prepare-build-environment" action.
        """
        used_files = cls._get_files_used_in_build_environment()

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_path in used_files:
            file_path = pl.Path(file_path)
            sha256.update(str(file_path).encode())
            sha256.update(str(file_path.stat().st_mode).encode())
            sha256.update(file_path.read_bytes())

        checksum = sha256.hexdigest()
        return checksum

    @classmethod
    def _get_build_environment_docker_image_name(cls):
        return f"package-builder-base-{cls._get_build_environment_files_checksum()}".lower()

    def _build_package_files(
            self,
            output_path: Union[str, pl.Path]
    ):
        """
        Build the basic structure for all packages.

            This creates a directory and then populates it with the basic structure required by most of the packages.

            It copies the certs, the configuration directories, etc.

            In the end, the structure will look like:
                certs/ca_certs.pem         -- The trusted SSL CA root list.
                bin/scalyr-agent-2         -- Main agent executable.
                bin/scalyr-agent-2-config  -- The configuration tool executable.
                build_info                 -- A file containing the commit id of the latest commit included in this package,
                                              the time it was built, and other information.
                VERSION                    -- File with current version of the agent.
                install_type               -- File with type of the installation.


        :param output_path: The output path where the result files are stored.
        """
        output_path = pl.Path(output_path)

        if output_path.exists():
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)

        # Write build_info file.
        build_info_path = output_path / "build_info"
        build_info_path.write_text(self._build_info)

        # Copy the monitors directory.
        monitors_path = output_path / "monitors"
        shutil.copytree(__SOURCE_ROOT__ / "monitors", monitors_path)
        recursively_delete_files_by_name(output_path / monitors_path, "README.md")

        # Add VERSION file.
        shutil.copy2(__SOURCE_ROOT__ / "VERSION", output_path / "VERSION")

        package_type_file_path = output_path / "install_type"
        package_type_file_path.write_text(type(self).INSTALL_TYPE)

    @abc.abstractmethod
    def _build(
            self,
            output_path: Union[str, pl.Path]
    ):
        """
        The implementation of the package build.
        :param output_path: Path for the build result.
        """
        pass


class FrozenBinaryPackageBuilder(PackageBuilder):
    """
    Package builder which is able to build the agent frozen binaries using the PyInstaller library..
    """

    FILES_USED_IN_BUILD_ENVIRONMENT = [
        __SOURCE_ROOT__ / "agent_build" / "requirements.txt",
        __SOURCE_ROOT__ / "agent_build" / "frozen-binary-builder-requirements.txt",
    ]

    def __init__(
            self,
            variant: str = None,
            no_versioned_file_name: bool = False,
    ):
        super(FrozenBinaryPackageBuilder, self).__init__(
            variant=variant,
            no_versioned_file_name=no_versioned_file_name
        )

        self._frozen_binary_output: Optional[pl.Path] = None

    def _build_frozen_binary(self):
        """
        Build the frozen binary using the PyInstaller library.
        """
        spec_file_path = __SOURCE_ROOT__ / "agent_build" / "pyinstaller_spec.spec"

        # Create the special folder in the package output directory where the Pyinstaller's output will be stored.
        # That may be useful during the debugging.
        pyinstaller_output = self._build_output_path / "frozen_binary"
        pyinstaller_output.mkdir(parents=True)

        self._frozen_binary_output = pyinstaller_output / "dist"

        # Run the PyInstaller.

        subprocess.check_call(
            [sys.executable, "-m", "PyInstaller", str(spec_file_path)],
            cwd=str(pyinstaller_output)
        )

        # Make frozen binaries executable.
        for child_path in self._frozen_binary_output.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        # Also build the frozen binary for the package test script, they will be used to test the packages later.
        package_test_pyinstaller_output = self._build_output_path / "frozen_binary_test"

        package_test_script_path = __SOURCE_ROOT__ / "tests" / "package_tests" / "package_test.py"

        subprocess.check_call([
            sys.executable, "-m", "PyInstaller", str(package_test_script_path),
            "--distpath", str(package_test_pyinstaller_output), "--onefile"
        ])

        # Make the package test frozen binaries executable
        for child_path in package_test_pyinstaller_output.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


class LinuxPackageBuilder(FrozenBinaryPackageBuilder):
    """
    The base package builder for all Linux packages.
    """
    PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH = __PARENT_DIR__ / "linux" / "prepare_build_environment.sh"
    BASE_DOCKER_IMAGE = "centos:7"
    DOCKERIZED = True

    def _build_package_files(
            self,
            output_path: Union[str, pl.Path]
    ):
        """
        Add files to the agent's install root which are common for all linux packages.
        """
        super(LinuxPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Add certificates.
        certs_path = output_path / "certs"
        self._add_certs(certs_path)

        # Misc extra files needed for some features.
        # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
        # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
        # using a package.
        misc_path = output_path / "misc"
        misc_path.mkdir()
        for f in [
            "Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"
        ]:
            shutil.copy2(__SOURCE_ROOT__ / "docker" / f, misc_path / f)


class LinuxFhsBasedPackageBuilder(LinuxPackageBuilder):
    """
    The package builder for the packages which follow the Linux FHS structure.
    For example deb, rpm, docker and k8s images.
    """

    INSTALL_TYPE = "package"

    def _build_package_files(
            self,
            output_path: Union[str, pl.Path]
    ):

        # The install root is located in the usr/share/scalyr-agent-2.
        install_root = output_path / "usr/share/scalyr-agent-2"
        super(LinuxFhsBasedPackageBuilder, self)._build_package_files(
            output_path=install_root
        )

        pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
        pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

        # Build frozen binaries.
        self._build_frozen_binary()
        bin_path = install_root / "bin"
        # Copy frozen binaries
        shutil.copytree(self._frozen_binary_output, bin_path)
        # Create symlink to the frozen binaries in the /usr/sbin folder.
        usr_sbin_path = self._package_files_path / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_symlink_path = self._package_files_path / "usr/sbin" / binary_path.name
            symlink_target_path = pl.Path("..", "share", "scalyr-agent-2", "bin", binary_path.name)
            binary_symlink_path.symlink_to(symlink_target_path)


class FpmBasedPackageBuilder(LinuxFhsBasedPackageBuilder):
    """
    Base image builder for packages which are produced by the 'fpm' packager.
    For example dep, rpm.
    """

    def __init__(
            self,
            variant: str = None,
            no_versioned_file_name: bool = False,
    ):
        super(FpmBasedPackageBuilder, self).__init__(
            variant=variant,
            no_versioned_file_name=no_versioned_file_name
        )
        # Path to generated changelog files.
        self._package_changelogs_path: Optional[pl.Path] = None

    def _build_package_files(
            self,
            output_path: Union[str, pl.Path]
    ):
        super(FpmBasedPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Copy config
        self._add_config(__SOURCE_ROOT__ / "config", output_path / "etc/scalyr-agent-2")

        # Copy the init.d script.
        init_d_path = output_path / "etc/init.d"
        init_d_path.mkdir(parents=True)
        shutil.copy2(
            __PARENT_DIR__ / "linux/deb_or_rpm/files/init.d/scalyr-agent-2",
            init_d_path / "scalyr-agent-2"
        )

    def _build(
            self,
            output_path: Union[str, pl.Path],
    ):
        """
        Build the deb or rpm package using the 'fpm' pckager.
        :param output_path: The path where the result package is stored.
        """

        self._build_package_files(
            output_path=self._package_files_path
        )

        if self._variant is not None:
            iteration_arg = "--iteration 1.%s" % self._variant
        else:
            iteration_arg = ""

        install_scripts_path = _AGENT_BUILD_PATH / "linux/deb_or_rpm/install-scripts"

        # generate changelogs
        self.create_change_logs()

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics and "
            "log files and transmit them to Scalyr."
        )
        fpm_command = [
            "fpm",
            "-s", "dir",
            "-a", "all",
            "-t", type(self).PACKAGE_TYPE,
            "-n", "scalyr-agent-2",
            "-v", self._package_version,
            "--chdir", str(self._package_files_path),
            "--license", "Apache 2.0",
            "--vendor", f"Scalyr {iteration_arg}",
            "--maintainer", "czerwin@scalyr.com",
            "--provides", "scalyr-agent-2",
            "--description", description,
            "--depends", 'bash >= 3.2',
            "--url", "https://www.scalyr.com",
            "--deb-user", "root",
            "--deb-group", "root",
            "--deb-changelog", str(self._package_changelogs_path / 'changelog-deb'),
            "--rpm-changelog", str(self._package_changelogs_path / 'changelog-rpm'),
            "--rpm-user", "root",
            "--rpm-group", "root",
            "--after-install", str(install_scripts_path / 'postinstall.sh'),
            "--before-remove", str(install_scripts_path / 'preuninstall.sh'),
            "--deb-no-default-config-files",
            "--no-deb-auto-config-files",
            "--config-files", "/etc/scalyr-agent-2/agent.json",
            "--directories", "/usr/share/scalyr-agent-2",
            "--directories", "/var/lib/scalyr-agent-2",
            "--directories", "/var/log/scalyr-agent-2",
            # NOTE 1: By default fpm won't preserve all the permissions we set on the files so we need
            # to use those flags.
            # If we don't do that, fpm will use 77X for directories and we don't really want 7 for
            # "group" and it also means config file permissions won't be correct.
            # NOTE 2: This is commented out since it breaks builds produced on builder VM where
            # build_package.py runs as rpmbuilder user (uid 1001) and that uid is preserved as file
            # owner for the package tarball file which breaks things.
            # On Circle CI uid of the user under which the package job runs is 0 aka root so it works
            # fine.
            # We don't run fpm as root on builder VM which means we can't use any other workaround.
            # Commenting this flag out means that original file permissions (+ownership) won't be
            # preserved which means we will also rely on postinst step fixing permissions for fresh /
            # new installations since those permissions won't be correct in the package artifact itself.
            # Not great.
            # Once we move all the build steps to Circle CI and ensure build_package.py runs as uid 0
            # we should uncomment this.
            # In theory it should work wth --*-user fpm flag, but it doesn't. Keep in mind that the
            # issue only applies to deb packages since --rpm-user and --rpm-root flag override the user
            # even if the --rpm-use-file-permissions flag is used.
            # "  --rpm-use-file-permissions "
            "--rpm-use-file-permissions",
            "--deb-use-file-permissions",
            # NOTE: Sadly we can't use defattrdir since it breakes permissions for some other
            # directories such as /etc/init.d and we need to handle that in postinst :/
            # "  --rpm-auto-add-directories "
            # "  --rpm-defattrfile 640"
            # "  --rpm-defattrdir 751"
            # "  -C root usr etc var",
        ]

        # Run fpm command and build the package.
        subprocess.check_call(
            fpm_command,
            cwd=str(self._build_output_path),
        )

    def create_change_logs(self):
        """Creates the necessary change logs for both RPM and Debian based on CHANGELOG.md.

        Creates two files named 'changelog-rpm' and 'changelog-deb'.  They
        will have the same content as CHANGELOG.md but formatted by the respective standards for the different
        packaging systems.
        """

        # We define a helper function named print_release_notes that is used down below.
        def print_release_notes(output_fp, notes, level_prefixes, level=0):
            """Emits the notes for a single release to output_fp.

            @param output_fp: The file to write the notes to
            @param notes: An array of strings containing the notes for the release. Some elements may be lists of strings
                themselves to represent sublists. Only three levels of nested lists are allowed. This is the same format
                returned by parse_change_log() method.
            @param level_prefixes: The prefix to use for each of the three levels of notes.
            @param level: The current level in the notes.
            """
            prefix = level_prefixes[level]
            for note in notes:
                if isinstance(note, list):
                    # If a sublist, then recursively call this function, increasing the level.
                    print_release_notes(output_fp, note, level_prefixes, level + 1)
                    if level == 0:
                        print("", file=output_fp)
                else:
                    # Otherwise emit the note with the prefix for this level.
                    print("%s%s" % (prefix, note), file=output_fp)

        self._package_changelogs_path = self._build_output_path / "package_changelog"
        self._package_changelogs_path.mkdir()

        # Handle the RPM log first.  We parse CHANGELOG.md and then emit the notes in the expected format.
        fp = open(self._package_changelogs_path / "changelog-rpm", "w")
        try:
            for release in common.parse_change_log():
                date_str = time.strftime("%a %b %d %Y", time.localtime(release["time"]))

                # RPM expects the leading line for a relesae to start with an asterisk, then have
                # the name of the person doing the release, their e-mail and then the version.
                print(
                    "* %s %s <%s> %s"
                    % (
                        date_str,
                        release["packager"],
                        release["packager_email"],
                        release["version"],
                    ),
                    file=fp,
                )
                print("", file=fp)
                print("Release: %s (%s)" % (release["version"], release["name"]), file=fp)
                print("", file=fp)
                # Include the release notes, with the first level with no indent, an asterisk for the second level
                # and a dash for the third.
                print_release_notes(fp, release["notes"], ["", " * ", "   - "])
                print("", file=fp)
        finally:
            fp.close()

        # Next, create the Debian change log.
        fp = open(self._package_changelogs_path / "changelog-deb", "w")
        try:
            for release in common.parse_change_log():
                # Debian expects a leading line that starts with the package, including the version, the distribution
                # urgency.  Then, anything goes until the last line for the release, which begins with two dashes.
                date_str = time.strftime(
                    "%a, %d %b %Y %H:%M:%S %z", time.localtime(release["time"])
                )
                print(
                    "scalyr-agent-2 (%s) stable; urgency=low" % release["version"], file=fp
                )
                # Include release notes with an indented first level (using asterisk, then a dash for the next level,
                # finally a plus sign.
                print_release_notes(fp, release["notes"], ["  * ", "   - ", "     + "])
                print(
                    " -- %s <%s>  %s"
                    % (
                        release["packager"],
                        release["packager_email"],
                        date_str,
                    ),
                    file=fp,
                )
        finally:
            fp.close()


class DebPackageBuilder(FpmBasedPackageBuilder):
    PACKAGE_TYPE = "deb"
    DOCKERIZED = True


class RpmPackageBuilder(FpmBasedPackageBuilder):
    PACKAGE_TYPE = "rpm"
    DOCKERIZED = True


class TarballPackageBuilder(LinuxPackageBuilder):
    """
    The builder for the tarball packages.
    """
    PACKAGE_TYPE = "tar"
    INSTALL_TYPE = "packageless"
    DOCKERIZED = True

    def _build_package_files(
            self,
            output_path: Union[str, pl.Path]
    ):

        super(TarballPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
        # in the tarball itself where the running process will store its state.
        data_dir = output_path / "data"
        data_dir.mkdir()
        log_dir = output_path / "log"
        log_dir.mkdir()

        self._add_config(
            __SOURCE_ROOT__ / "config", output_path / "config"
        )

    def _build(
            self,
            output_path: Union[str, pl.Path]
    ):

        self._build_package_files(
            output_path=self._package_files_path,
        )

        # Build frozen binary.
        self._build_frozen_binary()

        bin_path = self._package_files_path / "bin"
        # Copy frozen binaries
        shutil.copytree(self._frozen_binary_output, bin_path)

        if self._variant is None:
            base_archive_name = "scalyr-agent-%s" % self._package_version
        else:
            base_archive_name = "scalyr-agent-%s.%s" % (self._package_version, self._variant)

        output_name = (
            "%s.tar.gz" % base_archive_name
            if not self._no_versioned_file_name
            else "scalyr-agent.tar.gz"
        )

        tarball_output_path = self._build_output_path / output_name

        # Tar it up.
        tar = tarfile.open(tarball_output_path, "w:gz")
        tar.add(self._package_files_path, arcname=base_archive_name)
        tar.close()


class MsiWindowsPackageBuilder(FrozenBinaryPackageBuilder):
    PACKAGE_TYPE = "msi"
    INSTALL_TYPE = "package"
    PREPARE_BUILD_ENVIRONMENT_SCRIPT_PATH = _AGENT_BUILD_PATH / "windows/prepare_build_environment.ps1"
    DOCKERIZED = False

    # A GUID representing Scalyr products, used to generate a per-version guid for each version of the Windows
    # Scalyr Agent.  DO NOT MODIFY THIS VALUE, or already installed software on clients machines will not be able
    # to be upgraded.
    _scalyr_guid_ = uuid.UUID("{0b52b8a0-22c7-4d50-92c1-8ea3b258984e}")

    @property
    def _package_version(self) -> str:
        # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
        # requires X.X.X.X.  So, we convert if necessary.
        base_version = super(MsiWindowsPackageBuilder, self)._package_version
        if len(base_version.split(".")) == 5:
            parts = base_version.split(".")
            del parts[3]
            version = ".".join(parts)
            return version

        return base_version

    @classmethod
    def _prepare_build_environment(
        cls,
        cache_dir: Union[str, pl.Path] = None
    ):
        """
        Prepare the build environment to be able to build the windows msi package.
        """
        prepare_environment_script_path = _AGENT_BUILD_PATH / "windows/prepare_build_environment.ps1"
        subprocess.check_call(
            ["powershell", str(prepare_environment_script_path), str(cache_dir)]
        )

    def _build(
            self,
            output_path: Union[str, pl.Path]
    ):

        scalyr_dir = self._package_files_path / "Scalyr"

        # Build common package files.
        self._build_package_files(
            output_path=scalyr_dir
        )

        # Add root certificates.
        certs_path = scalyr_dir / "certs"
        self._add_certs(
            certs_path,
            intermediate_certs=False,
            copy_other_certs=False
        )

        # Build frozen binaries and copy them into bin folder.
        self._build_frozen_binary()
        bin_path = scalyr_dir / "bin"
        shutil.copytree(self._frozen_binary_output, bin_path)

        shutil.copy(
            _AGENT_BUILD_PATH / "windows/files/ScalyrShell.cmd",
            bin_path
        )

        # Copy config template.
        config_templates_dir_path = pl.Path(scalyr_dir / "config" / "templates")
        config_templates_dir_path.mkdir(parents=True)
        config_template_path = config_templates_dir_path / "agent_config.tmpl"
        shutil.copy2(__SOURCE_ROOT__ / "config" / "agent.json", config_template_path)
        config_template_path.write_text(config_template_path.read_text().replace("\n", "\r\n"))

        if self._variant is None:
            variant = "main"
        else:
            variant = self._variant

        # Generate a unique identifier used to identify this version of the Scalyr Agent to windows.
        product_code = uuid.uuid3(type(self)._scalyr_guid_, "ProductID:%s:%s" % (variant, self._package_version))
        # The upgrade code identifies all families of versions that can be upgraded from one to the other.  So, this
        # should be a single number for all Scalyr produced ones.
        upgrade_code = uuid.uuid3(type(self)._scalyr_guid_, "UpgradeCode:%s" % variant)

        wix_package_output = self._build_output_path / "wix"
        wix_package_output.mkdir(parents=True)

        wixobj_file_path = wix_package_output / "ScalyrAgent.wixobj"

        wxs_file_path = _AGENT_BUILD_PATH / "windows/scalyr_agent.wxs"

        # Compile WIX .wxs file.
        subprocess.check_call([
            "candle", "-nologo", "-out", str(wixobj_file_path), f'-dVERSION={self._package_version}',
            f'-dUPGRADECODE={upgrade_code}', f'-dPRODUCTCODE={product_code}',
            str(wxs_file_path)
        ])

        installer_name = f"ScalyrAgentInstaller-{self._package_version}.msi"
        installer_path = self._build_output_path / installer_name

        # Link compiled WIX files into msi installer.
        subprocess.check_call([
            "light", "-nologo", "-ext", "WixUtilExtension.dll", "-ext", "WixUIExtension",
            "-out", str(installer_path), str(wixobj_file_path), "-v"],
            cwd=str(scalyr_dir.absolute().parent)
        )


# Map package type names to package builder classes.
package_types_to_builders = {
    package_builder_cls.PACKAGE_TYPE: package_builder_cls
    for package_builder_cls in [
        DebPackageBuilder,
        RpmPackageBuilder,
        TarballPackageBuilder,
        MsiWindowsPackageBuilder
    ]
}


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "package_type",
        type=str,
        choices=list(package_types_to_builders.keys()),
        help="Type of the package to build.")

    parser.add_argument(
        "--locally", action="store_true",
        help="Some of the packages by default are build inside the docker to provide consistent build environment. "
             "Inside the docker, this script is executed once more, but with the '--locally' option, "
             "so it's aware that it should build the package directly in the docker."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_environment_parser = subparsers.add_parser("prepare-build-environment")
    prepare_environment_parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        help="Path to the directory which will be considered by the script is a cache. "
             "All 'cachable' intermediate results will be stored in it."
    )

    dump_checksum_parser = subparsers.add_parser("dump-checksum")
    dump_checksum_parser.add_argument(
        "checksum_file_path",
        help="The path of the output file with the checksum in it."
    )

    build_parser = subparsers.add_parser("build")

    build_parser.add_argument(
        "--output-dir", required=True, type=str, dest="output_dir",
        help="The directory where the result package has to be stored."
    )

    build_parser.add_argument(
        "--no-versioned-file-name",
        action="store_true",
        dest="no_versioned_file_name",
        default=False,
        help="If true, will not embed the version number in the artifact's file name.  This only "
             "applies to the `tarball` and container builders artifacts.",
    )

    build_parser.add_argument(
        "-v",
        "--variant",
        dest="variant",
        default=None,
        help="An optional string that is included in the package name to identify a variant "
             "of the main release created by a different packager.  "
             "Most users do not need to use this option.",
    )

    args = parser.parse_args()

    # Find the builder class.
    package_builder_cls = package_types_to_builders[args.package_type]

    if args.command == "dump-checksum":
        package_builder_cls.dump_build_environment_files_content_checksum(
            checksum_output_path=args.checksum_file_path
        )
        exit(0)

    if args.command == "prepare-build-environment":
        package_builder_cls.prepare_build_environment(
            cache_dir=args.cache_dir,
            locally=args.locally,
        )
        exit(0)

    if args.command == "build":
        output_path = pl.Path(args.output_dir)
        builder = package_builder_cls(
            variant=args.variant,
            no_versioned_file_name=args.no_versioned_file_name
        )

        builder.build(
            output_path=output_path,
            locally=args.locally,
        )


if __name__ == '__main__':
    main()
