import pathlib as pl
import tarfile
import shutil

from typing import Union

from agent_build.package_builder.linux import dockerized_linux_builder
from agent_build import common


class TarballPackageBuilder(dockerized_linux_builder.DockerizedPackageBuilder):

    @property
    def _package_type_name(self) -> str:
        return "tar"

    @property
    def _install_type_name(self):
        return "packageless"

    def _build_base_files(
            self,
            output_path: Union[str, pl.Path]
    ):

        super(TarballPackageBuilder, self)._build_base_files(
            output_path=output_path
        )

        # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
        # in the tarball itself where the running process will store its state.

        data_dir = output_path / "data"
        data_dir.mkdir()
        log_dir = output_path / "log"
        log_dir.mkdir()

        self._add_config(
            common.SOURCE_ROOT / "config", output_path / "config"
        )

    def _build(
            self,
            output_path: Union[str, pl.Path]
    ):

        self._build_base_files(
            output_path=self._package_filesystem_root,
        )

        self._build_frozen_binary()

        bin_path = self._package_filesystem_root / "bin"
        # Copy frozen binaries
        shutil.copytree(self._frozen_binary_output, bin_path)

        if self._variant is None:
            base_archive_name = "scalyr-agent-%s" % self.package_version
        else:
            base_archive_name = "scalyr-agent-%s.%s" % (self.package_version, self._variant)

        output_name = (
            "%s.tar.gz" % base_archive_name
            if not self._no_versioned_file_name
            else "scalyr-agent.tar.gz"
        )

        tarball_output_path = self._build_output_path / output_name

        # Tar it up.
        tar = tarfile.open(tarball_output_path, "w:gz")
        tar.add(self._package_filesystem_root, arcname=base_archive_name)
        tar.close()