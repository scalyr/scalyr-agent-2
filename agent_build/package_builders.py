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

"""
This module defines all possible packages of the Scalyr Agent and how they can be built.
"""


import json
import pathlib as pl
import shlex
import tarfile
import abc
import shutil
import subprocess
import time
import sys
import stat
import uuid
import os
import re
import io
import platform
from typing import Union, Optional, List, Dict, Type

from agent_build.tools import constants
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    with pl.Path(destination).open("w") as dest_fp:
        for file_path in file_paths:
            with pl.Path(file_path).open("r") as in_fp:
                for line in in_fp:
                    if convert_newlines:
                        line.replace("\n", "\r\n")
                    dest_fp.write(line)


def recursively_delete_files_by_name(
    dir_path: Union[str, pl.Path], *file_names: Union[str, pl.Path]
):
    """Deletes any files that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    @param file_names: A variable number of strings containing regular expressions that should match the file names of
        the files that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for file_name in file_names:
        matchers.append(re.compile(str(file_name)))

    # Walk down the current directory.
    for root, dirs, files in os.walk(dir_path.absolute()):
        # See if any of the files at this level match any of the matchers.
        for file_path in files:
            for matcher in matchers:
                if matcher.match(file_path):
                    # Delete it if it did match.
                    os.unlink(os.path.join(root, file_path))
                    break


def recursively_delete_dirs_by_name(root_dir: Union[str, pl.Path], *dir_names: str):
    """
    Deletes any directories that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    If a directory is found that needs to be deleted, all of it and its children are deleted.

    @param dir_names: A variable number of strings containing regular expressions that should match the file names of
        the directories that should be deleted.
    """

    # Compile the strings into actual regular expression match objects.
    matchers = []
    for dir_name in dir_names:
        matchers.append(re.compile(dir_name))

    # Walk down the file tree, top down, allowing us to prune directories as we go.
    for root, dirs, files in os.walk(root_dir):
        # Examine all directories at this level, see if any get a match
        for dir_path in dirs:
            for matcher in matchers:
                if matcher.match(dir_path):
                    shutil.rmtree(os.path.join(root, dir_path))
                    # Also, remove it from dirs so that we don't try to walk down it.
                    dirs.remove(dir_path)
                    break


# Special global collection of all builders. It can be used by CI/CD scripts to find needed package builder.
ALL_PACKAGE_BUILDERS: Dict[str, "PackageBuilder"] = {}


class PackageBuilder(abc.ABC):
    """
        Base abstraction for all Scalyr agent package builders. it can perform build of the package directly on the
    current system or inside docker.
        It also uses ':py:module:`agent_build.tools.environment_deployments` features to define and deploy its build
        environment in order to be able to perform the actual build.
    """

    # Type of the package to build.
    PACKAGE_TYPE: constants.PackageType = None

    # Add agent source code as a bundled frozen binary if True, or
    # add the source code as it is.
    USE_FROZEN_BINARIES: bool = True

    # Specify the name of the frozen binary, if it is used.
    FROZEN_BINARY_FILE_NAME = "scalyr-agent-2"

    # The type of the installation. For more info, see the 'InstallType' in the scalyr_agent/__scalyr__.py
    INSTALL_TYPE: str

    # Map package-specific architecture names to the architecture names that are used in build.
    PACKAGE_FILENAME_ARCHITECTURE_NAMES: Dict[constants.Architecture, str] = {}

    # The format string for the glob that has to match result package filename.
    # For now, the format string accepts:
    #   {arch}: architecture of the package.
    # See more in the "filename_glob" property of the class.
    RESULT_PACKAGE_FILENAME_GLOB: str

    # Monitors that are no included to to the build. Makes effect only with frozen binaries.
    EXCLUDED_MONITORS = []

    def __init__(
        self,
        architecture: constants.Architecture = constants.Architecture.UNKNOWN,
        base_docker_image: str = None,
        deployment_step_classes: List[Type[deployments.DeploymentStep]] = None,
        variant: str = None,
        no_versioned_file_name: bool = False,
    ):
        """
        :param architecture: Architecture of the package.
        :param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
        :param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.
        """
        # The path where the build output will be stored.
        self._build_output_path: Optional[pl.Path] = None

        # Folder with intermediate and temporary results of the build.
        self._intermediate_results_path: Optional[pl.Path] = None

        # The path of the folder where all files of the package will be stored.
        # May be help full for the debug purposes.
        self._package_files_path: Optional[pl.Path] = None

        self._variant = variant
        self._no_versioned_file_name = no_versioned_file_name

        self.architecture = architecture

        self.base_docker_image = base_docker_image

        # Create personal deployment for the package builder.
        self.deployment = deployments.Deployment(
            name=self.name,
            step_classes=deployment_step_classes or [],
            architecture=architecture,
            base_docker_image=base_docker_image,
        )

        if self.name in ALL_PACKAGE_BUILDERS:
            raise ValueError(
                f"The package builder with name: {self.name} already exists."
            )

        ALL_PACKAGE_BUILDERS[self.name] = self

    @property
    def name(self) -> str:
        """
        Unique name of the package builder. It considers the architecture of the package.
        """

        name = type(self).PACKAGE_TYPE.value

        # Omit architecture if unknown.
        if self.architecture != constants.Architecture.UNKNOWN:
            name = f"{name}_{self.architecture.value}"

        return name

    @property
    def filename_glob(self) -> str:
        """
        Final glob that has to match result package filename.
        """

        # Get appropriate glob format string and apply the appropriate architecture.
        package_specific_arch_name = type(self).PACKAGE_FILENAME_ARCHITECTURE_NAMES.get(
            self.architecture, ""
        )
        return type(self).RESULT_PACKAGE_FILENAME_GLOB.format(
            arch=package_specific_arch_name
        )

    def build(self, output_path: Union[str, pl.Path], locally: bool = False):
        """
        The function where the actual build of the package happens.
        :param output_path: Path to the directory where the resulting output has to be stored.
        :param locally: Force builder to build the package on the current system, even if meant to be done inside
            docker. This is needed to avoid loop when it is already inside the docker.
        """

        output_path = pl.Path(output_path).absolute()

        if output_path.exists():
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)

        # Build right here.
        if locally or not self.deployment.in_docker:
            self._build_output_path = pl.Path(output_path)
            self._package_files_path = self._build_output_path / "package_root"
            self._package_files_path.mkdir()
            self._intermediate_results_path = (
                self._build_output_path / "intermediate_results"
            )
            self._intermediate_results_path.mkdir()
            self._build(output_path=output_path)
            return

        # Build in docker.

        # First make sure that the deployment with needed images are ready.
        self.deployment.deploy()

        # To perform the build in docker we have to run the build_package.py script once more but in docker.
        build_package_script_path = pl.Path("/scalyr-agent-2/build_package.py")

        command_args = [
            "python3",
            str(build_package_script_path),
            self.name,
            "--output-dir",
            "/tmp/build",
            # Do not forget to specify this flag to avoid infinite docker build recursion.
            "--locally",
        ]

        command = shlex.join(command_args)

        # Run the docker build inside the result image of the deployment.
        base_image_name = self.deployment.result_image_name.lower()

        build_in_docker.build_stage(
            command=command,
            stage_name="build",
            architecture=self.architecture,
            image_name=f"agent-builder-{self.name}-{base_image_name}".lower(),
            base_image_name=base_image_name,
            output_path_mappings={output_path: pl.Path("/tmp/build")},
        )

    @property
    def _build_info(self) -> Optional[str]:
        """Returns a string containing the package build info."""

        build_info_buffer = io.StringIO()

        # We need to execute the git command in the source root.
        # Add in the e-mail address of the user building it.
        try:
            packager_email = (
                subprocess.check_output(
                    "git config user.email", shell=True, cwd=str(__SOURCE_ROOT__)
                )
                .decode()
                .strip()
            )
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

        # Determine the last commit from the log.
        commit_id = (
            subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
                shell=True,
                cwd=__SOURCE_ROOT__,
            )
            .decode()
            .strip()
        )

        print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

        # Include the branch just for safety sake.
        branch = (
            subprocess.check_output(
                "git branch | cut -d ' ' -f 2", shell=True, cwd=__SOURCE_ROOT__
            )
            .decode()
            .strip()
        )
        print("From branch: %s" % branch.strip(), file=build_info_buffer)

        # Add a timestamp.
        print(
            "Build time: %s"
            % str(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
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

        # Make sure config file has 640 permissions
        config_file_path = output_path / "agent.json"
        config_file_path.chmod(int("640", 8))

        # Make sure there is an agent.d directory regardless of the config directory we used.
        agent_d_path = output_path / "agent.d"
        agent_d_path.mkdir(exist_ok=True)
        # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
        # readable by others.
        agent_d_path.chmod(int("741", 8))

    @staticmethod
    def _add_certs(
        path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
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

    def _build_frozen_binary(
        self,
        output_path: Union[str, pl.Path],
    ):
        """
        Build the frozen binary using the PyInstaller library.
        """
        output_path = pl.Path(output_path)

        # Create the special folder in the package output directory where the Pyinstaller's output will be stored.
        # That may be useful during the debugging.
        pyinstaller_output = self._intermediate_results_path / "frozen_binary"
        pyinstaller_output.mkdir(parents=True, exist_ok=True)

        scalyr_agent_package_path = __SOURCE_ROOT__ / "scalyr_agent"

        # Create package info file. It will be read by agent in order to determine the package type and install root.
        # See '__determine_install_root_and_type' function in scalyr_agent/__scalyr__.py file.
        package_info_file = self._intermediate_results_path / "package_info.json"

        package_info = {"install_type": type(self).INSTALL_TYPE}
        package_info_file.write_text(json.dumps(package_info))

        # Add this package_info file in the 'scalyr_agent' package directory, near the __scalyr__.py file.
        add_data = {str(package_info_file): "scalyr_agent"}

        # Add monitor modules as hidden imports, since they are not directly imported in the agent's code.
        all_builtin_monitor_module_names = [
            mod_path.stem
            for mod_path in pl.Path(
                __SOURCE_ROOT__, "scalyr_agent", "builtin_monitors"
            ).glob("*.py")
            if mod_path.stem != "__init__"
        ]

        hidden_imports = []

        # We also have to filter platform dependent monitors.
        for monitor_name in all_builtin_monitor_module_names:
            if monitor_name in type(self).EXCLUDED_MONITORS:
                continue
            hidden_imports.append(f"scalyr_agent.builtin_monitors.{monitor_name}")

        # Add packages to frozen binary paths.
        paths_to_include = [
            str(scalyr_agent_package_path),
            str(scalyr_agent_package_path / "builtin_monitors"),
        ]

        # Add platform specific things.
        if platform.system().lower().startswith("linux"):
            tcollectors_path = pl.Path(
                __SOURCE_ROOT__,
                "scalyr_agent",
                "third_party",
                "tcollector",
                "collectors",
            )
            add_data.update(
                {tcollectors_path: tcollectors_path.relative_to(__SOURCE_ROOT__)}
            )

        # Create --add-data options from previously added files.
        add_data_options = []
        for src, dest in add_data.items():
            add_data_options.append("--add-data")
            add_data_options.append(f"{src}{os.path.pathsep}{dest}")

        # Create --hidden-import options from previously created hidden imports list.
        hidden_import_options = []
        for h in hidden_imports:
            hidden_import_options.append("--hidden-import")
            hidden_import_options.append(str(h))

        dist_path = pyinstaller_output / "dist"

        # Run the PyInstaller.
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                str(scalyr_agent_package_path / "agent_main.py"),
                "--onefile",
                "--distpath",
                str(dist_path),
                "--workpath",
                str(pyinstaller_output / "build"),
                "-n",
                type(self).FROZEN_BINARY_FILE_NAME,
                "--paths",
                ":".join(paths_to_include),
                *add_data_options,
                *hidden_import_options,
                "--exclude-module",
                "asyncio",
                "--exclude-module",
                "FixTk",
                "--exclude-module",
                "tcl",
                "--exclude-module",
                "tk",
                "--exclude-module",
                "_tkinter",
                "--exclude-module",
                "tkinter",
                "--exclude-module",
                "Tkinter",
                "--exclude-module",
                "sqlite",
            ],
            cwd=str(__SOURCE_ROOT__),
        )

        frozen_binary_path = dist_path / type(self).FROZEN_BINARY_FILE_NAME
        # Make frozen binary executable.
        frozen_binary_path.chmod(
            frozen_binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
        )

        # Copy resulting frozen binary to the output.
        output_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen_binary_path, output_path)

    def _build_package_files(self, output_path: Union[str, pl.Path]):
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

        # Create bin directory with executables.
        bin_path = output_path / "bin"
        bin_path.mkdir()

        if type(self).USE_FROZEN_BINARIES:
            self._build_frozen_binary(bin_path)
        else:
            source_code_path = output_path / "py"

            shutil.copytree(
                __SOURCE_ROOT__ / "scalyr_agent", source_code_path / "scalyr_agent"
            )

            agent_main_executable_path = bin_path / "scalyr-agent-2"
            agent_main_executable_path.symlink_to(
                pl.Path("..", "py", "scalyr_agent", "agent_main.py")
            )

            agent_config_executable_path = bin_path / "scalyr-agent-2-config"
            agent_config_executable_path.symlink_to(
                pl.Path("..", "py", "scalyr_agent", "config_main.py")
            )

            # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
            recursively_delete_dirs_by_name(
                source_code_path, r"\.idea", "tests", "__pycache__"
            )
            recursively_delete_files_by_name(
                source_code_path,
                r".*\.pyc",
                r".*\.pyo",
                r".*\.pyd",
                r"all_tests\.py",
                r".*~",
            )

    @abc.abstractmethod
    def _build(self, output_path: Union[str, pl.Path]):
        """
        The implementation of the package build.
        :param output_path: Path for the build result.
        """
        pass


class LinuxPackageBuilder(PackageBuilder):
    """
    The base package builder for all Linux packages.
    """

    EXCLUDED_MONITORS = [
        "windows_event_log_monitor",
        "windows_system_metrics",
        "windows_process_metrics",
    ]

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        """
        Add files to the agent's install root which are common for all linux packages.
        """
        super(LinuxPackageBuilder, self)._build_package_files(output_path=output_path)

        # Add certificates.
        certs_path = output_path / "certs"
        self._add_certs(certs_path)

        # Misc extra files needed for some features.
        # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
        # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
        # using a package.
        misc_path = output_path / "misc"
        misc_path.mkdir()
        for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
            shutil.copy2(__SOURCE_ROOT__ / "docker" / f, misc_path / f)


class LinuxFhsBasedPackageBuilder(LinuxPackageBuilder):
    """
    The package builder for the packages which follow the Linux FHS structure.
    (https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
    For example deb, rpm, docker and k8s images.
    """

    INSTALL_TYPE = "package"

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        # The install root is located in the usr/share/scalyr-agent-2.
        install_root = output_path / "usr/share/scalyr-agent-2"
        super(LinuxFhsBasedPackageBuilder, self)._build_package_files(
            output_path=install_root
        )

        pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
        pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

        bin_path = install_root / "bin"
        usr_sbin_path = self._package_files_path / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_symlink_path = (
                self._package_files_path / "usr/sbin" / binary_path.name
            )
            symlink_target_path = pl.Path(
                "..", "share", "scalyr-agent-2", "bin", binary_path.name
            )
            binary_symlink_path.symlink_to(symlink_target_path)


class ContainerPackageBuilder(LinuxFhsBasedPackageBuilder):
    """
    The base builder for all docker and kubernetes based images . It builds an executable script in the current working
     directory that will build the container image for the various Docker and Kubernetes targets.
     This script embeds all assets it needs in it so it can be a standalone artifact. The script is based on
     `docker/scripts/container_builder_base.sh`. See that script for information on it can be used."
    """

    # Path to the configuration which should be used in this build.
    CONFIG_PATH = None
    USE_FROZEN_BINARIES = False

    # Names of the result image that goes to dockerhub.
    RESULT_IMAGE_NAMES: List[str]

    def __init__(
        self,
        config_path: pl.Path,
        variant: str = None,
        no_versioned_file_name: bool = False,
    ):
        """
        :param config_path: Path to the configuration directory which will be copied to the image.
        :param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
        :param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.
        """
        super(ContainerPackageBuilder, self).__init__(
            architecture=constants.Architecture.UNKNOWN,
            variant=variant,
            no_versioned_file_name=no_versioned_file_name,
        )
        self.config_path = config_path

    def _build_package_files(self, output_path: Union[str, pl.Path]):
        super(ContainerPackageBuilder, self)._build_package_files(
            output_path=output_path
        )

        # Need to create some docker specific directories.
        pl.Path(output_path / "var/log/scalyr-agent-2/containers").mkdir()

        # Copy config
        self._add_config(
            config_source_path=self.config_path,
            output_path=self._package_files_path / "etc/scalyr-agent-2",
        )

    def _build(self, output_path: Union[str, pl.Path]):
        self._build_package_files(output_path=self._package_files_path)

        container_tarball_path = self._build_output_path / "scalyr-agent.tar.gz"

        # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
        # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
        # mainly Posix.
        with tarfile.open(container_tarball_path, "w:gz") as container_tar:

            for root, dirs, files in os.walk(self._package_files_path):
                to_copy = []
                for name in dirs:
                    to_copy.append(os.path.join(root, name))
                for name in files:
                    to_copy.append(os.path.join(root, name))

                for x in to_copy:
                    file_entry = container_tar.gettarinfo(
                        x, arcname=str(pl.Path(x).relative_to(self._package_files_path))
                    )
                    file_entry.uname = "root"
                    file_entry.gname = "root"
                    file_entry.uid = 0
                    file_entry.gid = 0

                    if file_entry.isreg():
                        with open(x, "rb") as fp:
                            container_tar.addfile(file_entry, fp)
                    else:
                        container_tar.addfile(file_entry)

    def build_image(
        self,
        image_names=None,
        registries: List[str] = None,
        tags: List[str] = None,
        push: bool = False,
        with_coverage: bool = False,
    ):
        """
        This function builds Agent docker image by using the dockerfile - 'docker/Docker.unified'.
        It passes to dockerfile its own package type through docker build arguments, so the same package builder
        will be executed inside the docker build to prepare inner container filesystem.
        :param image_names: The list of image names. By default uses image names that are specified in the
            package builder.
        :param registries: List of registries to push to.
        :param tags: List of tags.
        :param push: If True, push result image to the registries that are specified in the 'registries' argument.
            If False, then just export the result image to the local docker. NOTE: The local docker cannot handle
            multi-platform images, so it will only get image for its  platform.
        :param with_coverage: Makes docker image to run agent with enabled coverage measuring (Python 'coverage'
            library). Used only for testing.
        """

        registries = registries or [""]
        tags = tags or ["latest"]

        buildx_builder_name = "agent_image_buildx_builder"
        # Create docker buildx builder instance. # Without it the result image won't be pushed correctly
        # to the local registry.

        # check if builder already exists.
        ls_output = subprocess.check_output(["docker", "buildx", "ls"]).decode().strip()

        if buildx_builder_name not in ls_output:
            # Build new buildx builder
            subprocess.check_call(
                [
                    "docker",
                    "buildx",
                    "create",
                    # This option is important, without it the image won't be pushed to the local registry.
                    "--driver-opt=network=host",
                    "--name",
                    buildx_builder_name,
                ]
            )

        # Use builder.
        subprocess.check_call(
            [
                "docker",
                "buildx",
                "use",
                buildx_builder_name,
            ]
        )

        dockerfile_path = __SOURCE_ROOT__ / "Dockerfile"

        tag_options = []

        image_names = image_names or type(self).RESULT_IMAGE_NAMES

        for image_name in image_names:
            for registry in registries:
                for tag in tags:
                    tag_options.append("-t")
                    if registry:
                        registry_prefix = f"{registry}/"
                    else:
                        registry_prefix = ""
                    tag_options.append(f"{registry_prefix}{image_name}:{tag}")

        command_options = [
            "docker",
            "buildx",
            "build",
            *tag_options,
            "-f",
            str(dockerfile_path),
            "--build-arg",
            f"BUILD_TYPE={type(self).PACKAGE_TYPE.value}",
        ]

        # If we need to push, then specify all platforms.
        if push:
            command_options.append("--platform")
            command_options.append(
                constants.Architecture.X86_64.as_docker_platform.value
            )
            command_options.append("--platform")
            command_options.append(
                constants.Architecture.ARM64.as_docker_platform.value
            )

        if with_coverage:
            # Build image with enabled coverage measuring.
            command_options.append("--build-arg")
            command_options.append("MODE=with-coverage")

        if push:
            command_options.append("--push")
        else:
            command_options.append("--load")

        command_options.append(str(__SOURCE_ROOT__))

        subprocess.check_call(command_options)


class K8sPackageBuilder(ContainerPackageBuilder):
    """
    An image for running the agent on Kubernetes.
    """

    PACKAGE_TYPE = constants.PackageType.K8S
    RESULT_IMAGE_NAMES = ["scalyr/scalyr-k8s-agent"]


class DockerJsonPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to fetch logs via the file system (the container log
    directory is mounted to the agent container.)  This is the preferred way of running on Docker.
    This image is published to scalyr/scalyr-agent-docker-json.
    """

    PACKAGE_TYPE = constants.PackageType.DOCKER_JSON
    RESULT_IMAGE_NAMES = ["scalyr/scalyr-agent-docker-json"]


class DockerSyslogPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to receive logs from other containers via syslog.
    This is the deprecated approach (but is still published under scalyr/scalyr-docker-agent for
    backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog to help
    with the eventual migration.
    """

    PACKAGE_TYPE = constants.PackageType.DOCKER_SYSLOG
    RESULT_IMAGE_NAMES = [
        "scalyr/scalyr-agent-docker-syslog",
        "scalyr/scalyr-agent-docker",
    ]


class DockerApiPackageBuilder(ContainerPackageBuilder):
    """
    An image for running on Docker configured to fetch logs via the Docker API using docker_raw_logs: false
    configuration option.
    """

    PACKAGE_TYPE = constants.PackageType.DOCKER_API
    RESULT_IMAGE_NAMES = ["scalyr/scalyr-agent-docker-api"]


_CONFIGS_PATH = __SOURCE_ROOT__ / "docker"


# Create builders for each scalyr agent docker image. Those builders will be executed in the Dockerfile to
# create the filesystem for the image.
DOCKER_JSON_CONTAINER_BUILDER = DockerJsonPackageBuilder(
    config_path=_CONFIGS_PATH / "docker-json-config",
)

DOCKER_SYSLOG_CONTAINER_BUILDER = DockerSyslogPackageBuilder(
    config_path=_CONFIGS_PATH / "docker-syslog-config"
)

DOCKER_API_CONTAINER_BUILDER = DockerApiPackageBuilder(
    config_path=_CONFIGS_PATH / "docker-api-config"
)

K8S_CONTAINER_BUILDER = K8sPackageBuilder(config_path=_CONFIGS_PATH / "k8s-config")
