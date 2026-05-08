import os
import shutil
import tarfile
import pathlib as pl

from package_builders.utils.builder import Builder
from package_builders.utils.old_build_util import (
    build_base_files,
    make_directory,
    write_to_file,
    get_agent_version,
)

class TarballBuilder(Builder):
    NAME = "tarball"

    def __init__(self):
        super().__init__()

    def build(self, versioned_file_name: bool, output_dir: pl.Path = None):
        os.chdir(self.work_dir)
        self._build_tarball_package("main", get_agent_version(), versioned_file_name, output_dir)

    def _build_tarball_package(self, variant, version, versioned_file_name, output_dir: pl.Path):
        """Builds the scalyr-agent-2 tarball in the current working directory.

        @param variant: If not None, will add the specified string into the final tarball name. This allows for different
            tarballs to be built for the same type and same version.
        @param version: The agent version.
        @param versioned_file_name:  False if the version number should not be embedded in the artifact's file name.

        @return: The file name of the built tarball.
        """
        # Use build_base_files to build all of the important stuff in ./scalyr-agent-2
        build_base_files(install_type="tar")

        # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
        # in the tarball itself where the running process will store its state.
        make_directory("scalyr-agent-2/data")
        make_directory("scalyr-agent-2/log")
        make_directory("scalyr-agent-2/config/agent.d")
        # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
        # readable by others.
        os.chmod("scalyr-agent-2/config/agent.d", int("741", 8))

        # Create a file named packageless.  This signals to the agent that
        # this a tarball install instead of an RPM/Debian install, which changes
        # the default paths for the config, logs, data, etc directories.  See
        # configuration.py.
        write_to_file("1", "scalyr-agent-2/packageless")

        if variant is None or variant == "main":
            base_archive_name = "scalyr-agent-%s" % version
        else:
            base_archive_name = "scalyr-agent-%s.%s" % (version, variant)

        shutil.move("scalyr-agent-2", base_archive_name)

        output_name = (
            "%s.tar.gz" % base_archive_name
            if versioned_file_name
            else "scalyr-agent.tar.gz"
        )
        # Tar it up.
        output_dir.mkdir(parents=True, exist_ok=True)
        tar = tarfile.open(output_dir / output_name, "w:gz")
        tar.add(base_archive_name)
        tar.close()

        return output_name
