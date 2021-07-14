import pathlib as pl
import stat
import subprocess
import shutil
from typing import Union


from agent_build.package_builder.linux import dockerized_linux_builder
from agent_build import common

_PARENT_DIR = pl.Path(__file__).parent


class FpmBasedPackageBuilder(dockerized_linux_builder.DockerizedPackageBuilder):

    @property
    def _install_type_name(self):
        return "package"

    def _build_base_files(
            self,
            output_path: Union[str, pl.Path]
    ):
        install_root = output_path / "usr/share/scalyr-agent-2"

        super(FpmBasedPackageBuilder, self)._build_base_files(
            output_path=install_root
        )

        pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
        pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

        # Copy config
        self._add_config(common.SOURCE_ROOT / "config", output_path / "etc/scalyr-agent-2")

        # Copy the init.d script.
        init_d_path = output_path / "etc/init.d"
        init_d_path.mkdir(parents=True)
        shutil.copy2(
            _PARENT_DIR / "files/init.d/scalyr-agent-2",
            init_d_path / "scalyr-agent-2"
        )

    def _build(
            self,
            output_path: Union[str, pl.Path],
    ):

        """
        Build the deb or rpm package on the local system.
        :param build_info: The basic information about the build.
        :param output_path: The path where the result package is stored.
        """

        super(FpmBasedPackageBuilder, self)._build(
            output_path=output_path
        )

        self._build_base_files(
            output_path=self._package_filesystem_root
        )

        # Build frozen binaries.
        self._build_frozen_binary()
        bin_path = self._package_filesystem_root / "usr/share/scalyr-agent-2/bin"
        # Copy frozen binaries
        shutil.copytree(self._frozen_binary_output, bin_path)
        # Create symlink to the frozen binaries in the /usr/sbin folder.
        usr_sbin_path = self._package_filesystem_root / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_symlink_path = self._package_filesystem_root / "usr/sbin" / binary_path.name
            symlink_target_path = pl.Path("..", "share", "scalyr-agent-2", "bin", binary_path.name)
            binary_symlink_path.symlink_to(symlink_target_path)

        if self._variant is not None:
            iteration_arg = "--iteration 1.%s" % self._variant
        else:
            iteration_arg = ""

        install_scripts_path = _PARENT_DIR / "install-scripts"

        # prepare the command for the fpm packager.
        fpm_command = [
            "fpm",
            "-s",
            "dir",
            "-a",
            "all",
            "-t",
            self._package_type_name,
            "-n",
            "scalyr-agent-2",
            "-v",
            self.package_version,
            # "--debug"
            "--chdir",
            str(self._package_filesystem_root),
            "--license",
            "Apache 2.0",
            "--vendor",
            f"Scalyr {iteration_arg}",
            "--maintainer",
            "czerwin@scalyr.com",
            "--provides",
            "scalyr-agent-2",
            "--description",
            f"{self.description}",
            "--depends",
            "bash >= 3.2",
            "--url",
            "https://www.scalyr.com",
            "--deb-user",
            "root",
            "--deb-group",
            "root",
            # "--deb-changelog", "changelog-deb"
            "--rpm-user",
            "root",
            "--rpm-group",
            "root",
            # "--rpm-changelog", "changelog-rpm",
            "--before-install",
            str(install_scripts_path / "preinstall.sh"),
            "--after-install",
            str(install_scripts_path / "postinstall.sh"),
            "--before-remove",
            str(install_scripts_path / "preuninstall.sh"),
            "--deb-no-default-config-files",
            "--no-deb-auto-config-files",
            "--config-files",
            "/etc/scalyr-agent-2/agent.json",
            # NOTE: We leave those two files in place since they are symlinks which might have been
            # updated by scalyr-switch-python and we want to leave this in place - aka make sure
            # selected Python version is preserved on upgrade
            # "  --config-files /usr/share/scalyr-agent-2/bin/scalyr-agent-2 "
            # "  --config-files /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config "
            "--directories",
            "/usr/share/scalyr-agent-2",
            "--directories",
            "/var/lib/scalyr-agent-2",
            "--directories",
            "/var/log/scalyr-agent-2",
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

        subprocess.check_call(fpm_command, cwd=str(self._build_output_path))


class DebPackageBuilder(FpmBasedPackageBuilder):

    @property
    def _package_type_name(self) -> str:
        return "deb"


class RpmPackageBuilder(FpmBasedPackageBuilder):

    @property
    def _package_type_name(self) -> str:
        return "rpm"

