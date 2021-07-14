import pathlib as pl
import subprocess
import tarfile
import shutil

from typing import Union

from agent_build import common
from agent_build import docker_images
from agent_build.package_builder import package_filesystem, builder_inside_docker


# def build_tarball(
#         build_info: common.PackageBuildInfo,
#         output_path: Union[str, pl.Path]
# ):
#     package_output_path = pl.Path(output_path) / build_info.package_type
#
#     package_filesystem_root = package_output_path / "package_root"
#
#     package_filesystem.build_base_files(
#         build_info=build_info,
#         output_path=package_filesystem_root,
#     )
#
#     # =======
#
#     # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
#     # in the tarball itself where the running process will store its state.
#
#     data_dir = package_filesystem_root / "data"
#     data_dir.mkdir()
#     log_dir = package_filesystem_root / "log"
#     log_dir.mkdir()
#     config_dirs = package_filesystem_root / "config/agent.d"
#     config_dirs.mkdir(parents=True)
#
#     # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
#     # readable by others.
#     config_dirs.chmod(int("741", 8))
#
#     if build_info.variant is None:
#         base_archive_name = "scalyr-agent-%s" % build_info.package_version
#     else:
#         base_archive_name = "scalyr-agent-%s.%s" % (build_info.package_version, build_info.variant)
#
#     output_name = (
#         "%s.tar.gz" % base_archive_name
#         if not build_info.no_versioned_file_name
#         else "scalyr-agent.tar.gz"
#     )
#
#     tarball_output_path = output_path / output_name
#
#     # Tar it up.
#     tar = tarfile.open(tarball_output_path, "w:gz")
#     tar.add(base_archive_name)
#     tar.close()
#
#     # Build frozen binary
#     spec_file_path = SOURCE_ROOT / "agent_build" / "pyinstaller_spec.spec"
#     frozen_binary_output = package_output_path / "frozen_binary"
#
#     # The 'dist' (where the result frozen binary stored) and 'build' (intermediate build files) are folders where the
#     # PyInstaller outputs the build results.
#     frozen_binary_dist_path = frozen_binary_output / "dist"
#     work_path = frozen_binary_output / "build"
#     subprocess.check_call(
#         f"python3 -m PyInstaller {spec_file_path} --distpath {frozen_binary_dist_path} --workpath {work_path}",
#         shell=True,
#     )
#
#     bin_path = package_filesystem_root / "usr/share/scalyr-agent-2/bin"
#     # Copy frozen binaries
#     shutil.copytree(frozen_binary_dist_path, bin_path)
#
#     return output_name


class TarballPackageBuilder(builder_inside_docker.PackageBuilderInsideDocker):
    BASE_IMAGE = docker_images.FROZEN_BINARY_AND_FPM_BUILDER

    @property
    def package_type_name(self) -> str:
        return "tar"

    def _build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path]
    ):

        package_output_path = pl.Path(output_path) / self.package_type_name

        package_filesystem_root = package_output_path / "package_root"

        package_filesystem.build_base_files(
            build_info=build_info,
            package_type=self.package_type_name,
            output_path=package_filesystem_root,
        )

        # =======

        # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
        # in the tarball itself where the running process will store its state.

        data_dir = package_filesystem_root / "data"
        data_dir.mkdir()
        log_dir = package_filesystem_root / "log"
        log_dir.mkdir()

        # Copy the config folder.
        config_dir = package_filesystem_root / "config"
        shutil.copytree(
            common.SOURCE_ROOT / "config", config_dir
        )

        # Create agent.d folder.
        agent_d_dir = config_dir / "agent.d"
        agent_d_dir.mkdir()
        # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
        # readable by others.
        agent_d_dir.chmod(int("741", 8))

        # Write a special file to specify the type of the package.
        package_type_file = package_filesystem_root / "install_type"
        package_type_file.write_text(__scalyr__.InstallType.TARBALL_INSTALL.value)

        # Copy source code files to provide ability to run the agent on from source code on the client's
        # python interpreter.
        source_code_dir = package_filesystem_root / "source"
        source_code_dir.mkdir()
        shutil.copytree(common.SOURCE_ROOT / "scalyr_agent", source_code_dir, dirs_exist_ok=True)

        # Build frozen binary
        spec_file_path = common.SOURCE_ROOT / "agent_build" / "pyinstaller_spec.spec"
        frozen_binary_output = package_output_path / "frozen_binary"

        # The 'dist' (where the result frozen binary stored) and 'build' (intermediate build files) are folders where the
        # PyInstaller outputs the build results.
        frozen_binary_dist_path = frozen_binary_output / "dist"
        work_path = frozen_binary_output / "build"
        subprocess.check_call(
            f"python3 -m PyInstaller {spec_file_path} --distpath {frozen_binary_dist_path} --workpath {work_path}",
            shell=True,
        )

        bin_path = package_filesystem_root / "bin"
        # Copy frozen binaries
        shutil.copytree(frozen_binary_dist_path, bin_path)

        if build_info.variant is None:
            base_archive_name = "scalyr-agent-%s" % self.package_version
        else:
            base_archive_name = "scalyr-agent-%s.%s" % (self.package_version, build_info.variant)

        output_name = (
            "%s.tar.gz" % base_archive_name
            if not build_info.no_versioned_file_name
            else "scalyr-agent.tar.gz"
        )

        tarball_output_path = package_output_path / output_name

        # Tar it up.
        tar = tarfile.open(tarball_output_path, "w:gz")
        tar.add(package_filesystem_root, arcname=base_archive_name)
        tar.close()