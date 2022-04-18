from typing import Union
import pathlib as pl
import shutil
import re
import os

from agent_build.tools import constants


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


class AgentFilesystemBuilder:
    def __init__(
            self,
            output_path: pl.Path,
    ):
        self._package_root_path = output_path

    @staticmethod
    def _add_certs(
        path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
    ):
        """
        Create needed certificates files in the specified path.
        """

        path = pl.Path(path)
        path.mkdir(parents=True)
        source_certs_path = constants.SOURCE_ROOT / "certs"

        cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

        if intermediate_certs:
            cat_files(
                source_certs_path.glob("*_intermediate.pem"),
                path / "intermediate_certs.pem",
            )
        if copy_other_certs:
            for cert_file in source_certs_path.glob("*.pem"):
                shutil.copy(cert_file, path / cert_file.name)

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

        # Also iterate through all files in the agent.d and set appropriate permissions.
        for child_path in agent_d_path.iterdir():
            if child_path.is_file():
                child_path.chmod(int("640", 8))

    @property
    def _agent_install_root_path(self) -> pl.Path:
        """
        The path to the root directory with all agent-related files.
        By the default, the install root of the agent is the same as the root of the whole package.
        """
        return self._package_root_path

    def _build_package_files(self):
        """
        This method builds all files of the package.
        """

        # Clear previously used build folder, if exists.
        if self._package_root_path.exists():
            shutil.rmtree(self._package_root_path)

        self._package_root_path.mkdir(parents=True)

        # Build files in the agent's install root.
        self._build_agent_install_root()

    def _build_agent_install_root(self):
        """
        Build the basic structure of the install root.

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

        """

        if self._agent_install_root_path.exists():
            shutil.rmtree(self._agent_install_root_path)

        self._agent_install_root_path.mkdir(parents=True)

        # Copy the monitors directory.
        monitors_path = self._agent_install_root_path / "monitors"
        shutil.copytree(constants.SOURCE_ROOT / "monitors", monitors_path)
        recursively_delete_files_by_name(
            self._agent_install_root_path / monitors_path, "README.md"
        )

        # Add VERSION file.
        shutil.copy2(
            constants.SOURCE_ROOT / "VERSION", self._agent_install_root_path / "VERSION"
        )

        # Create bin directory with executables.
        bin_path = self._agent_install_root_path / "bin"
        bin_path.mkdir()

        source_code_path = self._agent_install_root_path / "py"

        shutil.copytree(
            constants.SOURCE_ROOT / "scalyr_agent", source_code_path / "scalyr_agent"
        )

        agent_main_executable_path = bin_path / "scalyr-agent-2"
        agent_main_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "agent_main.py")
        )

        agent_config_executable_path = bin_path / "scalyr-agent-2-config"
        agent_config_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "config_main.py")
        )

        # Write install_info file inside the "scalyr_agent" package.
        build_info_path = source_code_path / "scalyr_agent" / "install_info.json"
        build_info_path.write_text(self._install_info_str)

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


class LinuxAgentFilesystemBuilder(AgentFilesystemBuilder):
    def _build_agent_install_root(self):
        """
        Add files to the agent's install root which are common for all linux packages.
        """
        super(LinuxAgentFilesystemBuilder, self)._build_agent_install_root()

        # Add certificates.
        certs_path = self._agent_install_root_path / "certs"
        self._add_certs(certs_path)

        # Misc extra files needed for some features.
        # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
        # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
        # using a package.
        misc_path = self._agent_install_root_path / "misc"
        misc_path.mkdir()
        for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
            shutil.copy2(constants.SOURCE_ROOT / "docker" / f, misc_path / f)


class LinuxFhsAgentFilesystemBuilder(LinuxAgentFilesystemBuilder):
    """
    The package builder for the packages which follow the Linux FHS structure.
    (https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
    For example deb, rpm, docker and k8s images.
    """

    INSTALL_TYPE = "package"

    @property
    def _agent_install_root_path(self) -> pl.Path:
        # The install root for FHS based packages is located in the usr/share/scalyr-agent-2.
        original_install_root = super(
            LinuxFhsAgentFilesystemBuilder, self
        )._agent_install_root_path
        return original_install_root / "usr/share/scalyr-agent-2"

    def _build_package_files(self):

        super(LinuxFhsAgentFilesystemBuilder, self)._build_package_files()

        pl.Path(self._package_root_path, "var/log/scalyr-agent-2").mkdir(parents=True)
        pl.Path(self._package_root_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

        bin_path = self._agent_install_root_path / "bin"
        usr_sbin_path = self._package_root_path / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_symlink_path = (
                self._package_root_path / "usr/sbin" / binary_path.name
            )
            symlink_target_path = pl.Path(
                "..", "share", "scalyr-agent-2", "bin", binary_path.name
            )
            binary_symlink_path.symlink_to(symlink_target_path)


class ContainerPackageBuilder(LinuxFhsAgentFilesystemBuilder):
    """
    The base builder for all docker and kubernetes based images . It builds an executable script in the current working
     directory that will build the container image for the various Docker and Kubernetes targets.
     This script embeds all assets it needs in it so it can be a standalone artifact. The script is based on
     `docker/scripts/container_builder_base.sh`. See that script for information on it can be used."
    """

    # Path to the configuration which should be used in this build.
    CONFIG_PATH = None

    # Names of the result image that goes to dockerhub.
    RESULT_IMAGE_NAMES: List[str]

    FILE_GLOBS_USED_IN_IMAGE_BUILD: List[pl.Path] = []

    def __init__(
        self,
    ):
        """
        :param config_path: Path to the configuration directory which will be copied to the image.
        :param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
        :param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.
        """
        self._name = name
        self.dockerfile_path = constants.SOURCE_ROOT / "agent_build/docker/Dockerfile"

        super(ContainerPackageBuilder, self).__init__()

        self.base_image_deployment_step_cls = base_image_deployment_step_cls

        self.config_path = config_path

    @property
    def name(self) -> str:
        # Container builders are special since we have an instance per Dockerfile since different
        # Dockerfile represents a different builder
        return self._name

    def _build_package_files(self):
        super(ContainerPackageBuilder, self)._build_package_files()

        # Need to create some docker specific directories.
        pl.Path(self._package_root_path / "var/log/scalyr-agent-2/containers").mkdir()

        # Copy config
        self._add_config(
            config_source_path=self.config_path,
            output_path=self._package_root_path / "etc/scalyr-agent-2",
        )

    def _build(self):
        self._build_package_files()

        container_tarball_path = self._build_output_path / "scalyr-agent.tar.gz"

        # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
        # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
        # mainly Posix.
        with tarfile.open(container_tarball_path, "w:gz") as container_tar:

            for root, dirs, files in os.walk(self._package_root_path):
                to_copy = []
                for name in dirs:
                    to_copy.append(os.path.join(root, name))
                for name in files:
                    to_copy.append(os.path.join(root, name))

                for x in to_copy:
                    file_entry = container_tar.gettarinfo(
                        x, arcname=str(pl.Path(x).relative_to(self._package_root_path))
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

    def build_filesystem_tarball(self, output_path: pl.Path):
        super(ContainerPackageBuilder, self).build(locally=True)

        # Also copy result tarball to the given path.
        output_path.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(self._build_output_path / "scalyr-agent.tar.gz", output_path)


def _add_certs(
        path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
):
    """
    Create needed certificates files in the specified path.
    """

    path = pl.Path(path)
    path.mkdir(parents=True)
    source_certs_path = constants.SOURCE_ROOT / "certs"

    cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

    if intermediate_certs:
        cat_files(
            source_certs_path.glob("*_intermediate.pem"),
            path / "intermediate_certs.pem",
        )
    if copy_other_certs:
        for cert_file in source_certs_path.glob("*.pem"):
            shutil.copy(cert_file, path / cert_file.name)


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

    # Also iterate through all files in the agent.d and set appropriate permissions.
    for child_path in agent_d_path.iterdir():
        if child_path.is_file():
            child_path.chmod(int("640", 8))


def build_agent_base_files(
        copy_agent_source: bool,
        output_path: pl.Path,
        install_info_str,
        config_path: pl.Path = None,
):
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    # Copy the monitors directory.
    monitors_path = output_path / "monitors"
    shutil.copytree(constants.SOURCE_ROOT / "monitors", monitors_path)
    recursively_delete_files_by_name(
        output_path / monitors_path, "README.md"
    )

    # Add VERSION file.
    shutil.copy2(
        constants.SOURCE_ROOT / "VERSION", output_path / "VERSION"
    )

    # Create bin directory with executables.
    bin_path = output_path / "bin"
    bin_path.mkdir()

    if config_path:
        _add_config(
            config_source_path=config_path,
            output_path=output_path / "config"
        )

    if copy_agent_source:
        source_code_path = output_path / "py"

        shutil.copytree(
            constants.SOURCE_ROOT / "scalyr_agent", source_code_path / "scalyr_agent"
        )

        agent_main_executable_path = bin_path / "scalyr-agent-2"
        agent_main_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "agent_main.py")
        )

        agent_config_executable_path = bin_path / "scalyr-agent-2-config"
        agent_config_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "config_main.py")
        )

        # Write install_info file inside the "scalyr_agent" package.
        build_info_path = source_code_path / "scalyr_agent" / "install_info.json"
        build_info_path.write_text(install_info_str)

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


def build_linux_agent_files(
        copy_agent_source: bool,
        output_path: pl.Path,
        install_info_str,
        config_path: pl.Path = None
):
    build_agent_base_files(
        copy_agent_source=copy_agent_source,
        output_path=output_path,
        install_info_str=install_info_str,
        config_path=config_path
    )

    """
    Add files to the agent's install root which are common for all linux packages.
    """

    # Add certificates.
    certs_path = output_path / "certs"
    _add_certs(certs_path)

    # Misc extra files needed for some features.
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
    # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
    # using a package.
    misc_path = output_path / "misc"
    misc_path.mkdir()
    for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
        shutil.copy2(constants.SOURCE_ROOT / "docker" / f, misc_path / f)


def build_linux_lfs_agent_files(
        copy_agent_source: bool,
        output_path: pl.Path,
        install_info_str,
        config_path: pl.Path = None
):

    agent_install_root = output_path / "usr/share/scalyr-agent-2"
    build_linux_agent_files(
        copy_agent_source=copy_agent_source,
        output_path=agent_install_root,
        install_info_str=install_info_str
    )

    pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
    pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

    if config_path:
        _add_config(
            config_source_path=config_path,
            output_path=output_path / "etc/scalyr-agent-2"
        )

    bin_path = agent_install_root / "bin"
    usr_sbin_path = output_path / "usr/sbin"
    usr_sbin_path.mkdir(parents=True)
    for binary_path in bin_path.iterdir():
        binary_symlink_path = (
                output_path / "usr/sbin" / binary_path.name
        )
        symlink_target_path = pl.Path(
            "..", "share", "scalyr-agent-2", "bin", binary_path.name
        )
        binary_symlink_path.symlink_to(symlink_target_path)