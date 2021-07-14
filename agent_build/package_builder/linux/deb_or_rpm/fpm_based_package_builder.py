import pathlib as pl
import stat
import subprocess
import shutil
from typing import Union


from agent_build.package_builder import builder_inside_docker, linux
from agent_build import docker_images
from agent_build import common
from agent_build.package_builder.linux import linux_builder

__all__ = ["FpmBasedPackageBuilder"]

_PARENT_DIR = pl.Path(__file__).parent


class FpmBasedPackageBuilder(builder_inside_docker.PackageBuilderInsideDocker):
    BASE_IMAGE = docker_images.FROZEN_BINARY_AND_FPM_BUILDER

    def _build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path],
    ):

        """
        Build the deb or rpm package on the local system.
        :param build_info: The basic information about the build.
        :param output_path: The path where the result package is stored.
        """

        super(FpmBasedPackageBuilder, self)._build(
            build_info=build_info,
            output_path=output_path
        )

        # package_output_path = pl.Path(output_path) / self.package_type_name
        #
        # spec_file_path = common.SOURCE_ROOT / "agent_build" / "pyinstaller_spec.spec"
        # frozen_binary_output = package_output_path / "frozen_binary"
        #
        # frozen_binary_dist_path = frozen_binary_output / "dist"
        # work_path = frozen_binary_output / "build"
        # subprocess.check_call(
        #     f"python3 -m PyInstaller {spec_file_path} --distpath {frozen_binary_dist_path} --workpath {work_path}",
        #     shell=True,
        # )
        self._build_frozen_binary()

        if build_info.variant is not None:
            iteration_arg = "--iteration 1.%s" % build_info.variant
        else:
            iteration_arg = ""

        install_scripts_path = _PARENT_DIR / "install-scripts"

        # package_filesystem_root = self._package_output_path / "package_root"

        # TODO: Uncomment that to continue working on enabling the systemd support.
        # fpm_pleaserun_command = f"""
        # fpm -s pleaserun -t dir --package {package_filesystem_root} --name scalyr-agent-2 --pleaserun-name scalyr-agent-2 "/usr/sbin/scalyr-agent-2 start --no-fork"
        # """
        #
        # subprocess.check_call(
        #     fpm_pleaserun_command, shell=True
        # )

        linux.build_common_docker_and_package_files(
            build_info=build_info,
            package_type=self.package_type_name,
            output_path=self._package_filesystem_root,
            base_configs_path=common.SOURCE_ROOT / "config",
        )

        package_type_file_path = self._package_filesystem_root / "usr/share/scalyr-agent-2/install_type"
        package_type_file_path.write_text("package")

        bin_path = self._package_filesystem_root / "usr/share/scalyr-agent-2/bin"
        # Copy frozen binaries
        shutil.copytree(self._frozen_binary_output, bin_path)

        # Create symlink to the frozen binaries
        usr_sbin_path = self._package_filesystem_root / "usr/sbin"
        usr_sbin_path.mkdir(parents=True)
        for binary_path in bin_path.iterdir():
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
            binary_symlink_path = self._package_filesystem_root / "usr/sbin" / binary_path.name
            binary_rel_path = pl.Path("..", "share", "scalyr-agent-2", "bin", binary_path.name)

            binary_symlink_path.symlink_to(binary_rel_path)


        # prepare the command for the fpm packager.
        fpm_command = [
            "fpm",
            "-s",
            "dir",
            "-a",
            "all",
            "-t",
            self.package_type_name,
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

        subprocess.check_call(fpm_command, cwd=str(self._package_output_path))


