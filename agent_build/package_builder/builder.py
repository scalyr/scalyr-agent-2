import abc
import argparse
import pathlib as pl
import shutil
import re
import os
import io
import subprocess
import time
import sys
import stat
from typing import Union, List, Optional

from agent_build import common

__all__ = ["PackageBuilder"]

_SOURCE_CERTS_PATH = common.SOURCE_ROOT / "certs"

def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    dest_fp = open(destination, "w")
    for file_path in file_paths:
        in_fp = open(file_path, "r")
        for line in in_fp:
            if convert_newlines:
                line.replace("\n", "\r\n")
            dest_fp.write(line)
        in_fp.close()
    dest_fp.close()


def add_certs(path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True):
    path = pl.Path(path)
    source_certs_path = common.SOURCE_ROOT / "certs"

    cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

    if intermediate_certs:
        cat_files(
            source_certs_path.glob("*_intermediate.pem"),
            path / "intermediate_certs.pem",
        )
    if copy_other_certs:
        for cert_file in source_certs_path.glob("*.pem"):
            shutil.copy(cert_file, path / cert_file.name)


def recursively_delete_files_by_name(
        dir_path: Union[str, pl.Path],
        *file_names: Union[str, pl.Path]
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
            remove_it = False
            for matcher in matchers:
                if matcher.match(file_path):
                    remove_it = True
            # Delete it if it did match.
            if remove_it:
                os.unlink(os.path.join(root, file_path))


class PackageBuilder(abc.ABC):
    PACKAGE_TYPE_NAME = None
    BASE_DOCKER_IMAGE = None

    def __init__(
            self,
            cache_dir: Union[str, pl.Path] = None,
            locally=False
    ):
        self._locally = locally

        if cache_dir is not None:
            cache_dir = pl.Path(cache_dir)

        self._cache_dir = cache_dir

        self._package_output_path: Optional[pl.Path] = None

        self._package_filesystem_root: Optional[pl.Path] = None

        self._certs_path: Optional[pl.Path] = None

        self._frozen_binary_dist_path: Optional[pl.Path] = None

    def _get_class_attribute_and_null_check(self, attr):
        if attr is None:
            raise NotImplementedError(f"The class attribute '{attr}' is not set.")

        return attr

    @property
    def package_type_name(self) -> str:
        print(type(self))
        return self._get_class_attribute_and_null_check(type(self).PACKAGE_TYPE_NAME)

    @property
    def build_info(self) -> Optional[str]:
        """Returns a string containing the build info."""

        build_info_buffer = io.StringIO()

        # We need to execute the git command in the source root.
        # Add in the e-mail address of the user building it.
        try:
            packager_email = subprocess.check_output(
                "git config user.email", shell=True, cwd=str(common.SOURCE_ROOT)
            ).decode().strip()
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

        # Determine the last commit from the log.
        commit_id = subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
                shell=True,
                cwd=common.SOURCE_ROOT,
        ).decode().strip()

        print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

        # Include the branch just for safety sake.
        branch = subprocess.check_output(
            "git branch | cut -d ' ' -f 2", shell=True, cwd=common.SOURCE_ROOT
        ).decode().strip()
        print("From branch: %s" % branch.strip(), file=build_info_buffer)

        # Add a timestamp.
        print(
            "Build time: %s" % str(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
            file=build_info_buffer,
        )

        return build_info_buffer.getvalue()

    @property
    def description(self) -> str:
        return (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics and "
            "log files and transmit them to Scalyr."
    )

    @property
    def package_version(self) -> str:
        return pl.Path(common.SOURCE_ROOT, "VERSION").read_text().strip()

    @classmethod
    def _get_used_files(cls):
        return []

    @classmethod
    def dump_dependencies_content_checksum(
            cls,
            content_checksum_path: Union[str, pl.Path]
    ):
        """
        Dump the checksum of the content of the base docker images.

        :param content_checksum_path: Has the same CI/CD purpose as the previous one. If specified, the function dumps the
            file with the checksum of all the content that is used to build base docker images and skips the build.
            This checksum can be used by CI/CD as the cache key for base images.
        """
        checksum = common.get_files_sha256_checksum(cls._get_used_files())

        content_checksum_path = pl.Path(content_checksum_path)
        content_checksum_path.parent.mkdir(exist_ok=True, parents=True)
        content_checksum_path.write_text(checksum.hexdigest())

    @classmethod
    def prepare_dependencies(
            cls,
            cache_dir: Union[str, pl.Path] = None,
    ):
        pass

    @abc.abstractmethod
    def _build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path]
    ):
        pass

    def _build_frozen_binary(self):
        spec_file_path = common.SOURCE_ROOT / "agent_build" / "pyinstaller_spec.spec"

        self._frozen_binary_build_output = self._package_output_path / "frozen_binary"
        self._frozen_binary_output = self._frozen_binary_build_output / "dist"

        work_path = self._frozen_binary_build_output / "build"
        subprocess.check_call(
            f"python -m PyInstaller {spec_file_path} --distpath {self._frozen_binary_output} --workpath {work_path}",
            shell=True,
        )

        # Make frozen binaries executable.
        for child_path in self._frozen_binary_output.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        # Also build the frozen binary for the test script.
        self._frozen_binary_test_output = self._package_output_path / "frozen_binary_test"

        distribution_test_script_path = common.SOURCE_ROOT / "tests" / "distribution_tests" / "test_scalyr-agent.py"

        subprocess.check_call(
            f"python -m PyInstaller {distribution_test_script_path} --distpath {self._frozen_binary_test_output} --onefile",
            shell=True,
        )

        # Make the frozen binary for test executable
        for child_path in self._frozen_binary_test_output.iterdir():
            child_path.chmod(child_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


    def build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path]
    ):
        self._package_output_path = pl.Path(output_path) / self.package_type_name

        self._package_filesystem_root = self._package_output_path / "package_root"

        self._certs_path = self._package_filesystem_root / "certs"

        self._build(
            build_info=build_info,
            output_path=output_path
        )

    def build_base_files(
            self,
            output_path: Union[str, pl.Path]
    ):
        """
        Build the basic structure for a package..

            This creates a directory and then populates it with the basic structure required by most of the packages.

            It copies the certs, the configuration directories, etc.

            In the end, the structure will look like:
                certs/ca_certs.pem         -- The trusted SSL CA root list.
                bin/scalyr-agent-2         -- Symlink to the agent_main.py file to run the agent.
                bin/scalyr-agent-2-config  -- Symlink to config_main.py to run the configuration tool
                build_info                 -- A file containing the commit id of the latest commit included in this package,
                                              the time it was built, and other information.

        :param build_info: The basic information about the build.
        :param output_path: The output path where the result files are stored.
        """
        output_path = pl.Path(output_path)


        if output_path.exists():
            print("444", output_path)
            shutil.rmtree(output_path)

        output_path.mkdir(parents=True)

        # Write build_info file.
        build_info_path = output_path / "build_info"
        build_info_path.write_text(self.build_info)

        # Copy the monitors directory.
        monitors_path = output_path / "monitors"
        shutil.copytree(common.SOURCE_ROOT / "monitors", monitors_path)
        recursively_delete_files_by_name(output_path / monitors_path, "README.md")

        # Misc extra files needed for some features.
        # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
        # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
        # using a package.
        misc_path = output_path / "misc"
        misc_path.mkdir()
        for f in [
            "Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"
        ]:
            shutil.copy2(common.SOURCE_ROOT / "docker" / f, misc_path / f)

        # Add VERSION file.
        shutil.copy2(common.SOURCE_ROOT / "VERSION", output_path / "VERSION")

    @classmethod
    def get_builder_path(cls):
        return pl.Path(sys.modules[cls.__module__].__file__)


    @classmethod
    def handle_command_line(cls, argv):
        parser = argparse.ArgumentParser()

        subparsers = parser.add_subparsers(dest="command")

        prepare_environment_parser = subparsers.add_parser("prepare-environment")

        prepare_environment_parser.add_argument(
            "--content-checksum-path", type=str, dest="content_checksum_path",
            help="Calculate the checksum of the content of all files that are used in the build and dump it into the file"
                 " located in the specified path. This is useful to calculate the cache key for CI/CD"
        )

        prepare_environment_parser.add_argument(
            "--cache-dependencies-path", type=str, dest="cache_dependencies_path",
            help="The directory where the build dependencies has to be cached. This should be mostly "
                 "used by CI/CD to reduce the build time."
        )

        build_parser = subparsers.add_parser("build")
        build_parser.add_argument(
            "--no-versioned-file-name",
            action="store_true",
            dest="no_versioned_file_name",
            default=False,
            help="If true, will not embed the version number in the artifact's file name.  This only "
                 "applies to the `tarball` and container builders artifacts.",
        )

        parser.add_argument(
            "--output-dir", required=True, type=str, dest="output_dir",
            help="The directory where the result package has to be stored."
        )

        parser.add_argument(
            "--locally", action="store_true",
            help="Some of the packages by default are build inside the docker to provide consistent build environment."
                 "Inside the docker this script is executed once more, but with the '--locally' option, "
                 "so it's aware that it should build the package directly in the docker."
        )


        args = parser.parse_args(args=argv)

        if args.command == "prepare-environment":
            cls.prepare_dependencies()
        elif args.command == "build":
            instance = cls()
            output_path = pl.Path(args.output_dir)
            output_path.mkdir(exist_ok=True, parents=True)
            build_info = common.PackageBuildInfo(
                build_summary=common.get_build_info(),
                no_versioned_file_name=args.no_versioned_file_name
            )
            instance.build(
                build_info=build_info,
                output_path=output_path
            )


        a=10









        # # Write a special file to specify the type of the package.
        # package_type_file = output_path / "install_type"
        # package_type_file.write_text(package_type)
    # @classmethod
    # def handle_command_line_arguments(cls, argv: List[str]):
    #     cache_parser = argparse.ArgumentParser()
    #
    #     cache_parser.add_argument(
    #         "--content-checksum-path", type=str, dest="content_checksum_path",
    #         help="Calculate the checksum of the content of all files that are used in the build and dump it into the file"
    #              " located in the specified path. This is useful to calculate the cache key for CI/CD"
    #     )
    #
    #     cache_parser.add_argument(
    #         "--cache-dependencies-path", type=str, dest="cache_dependencies_path",
    #         help="The directory where the build dependencies has to be cached. This should be mostly "
    #              "used by CI/CD to reduce the build time."
    #     )
    #
    #     cache_args, build_argv = cache_parser.parse_known_args(args=argv)
    #
    #     if cache_args.content_checksum_path:
    #         # this is a special case when we dump the checksum of all files which are used in the build. This checksum
    #         # them can be used as a key for CI/CD cache.
    #         builder = cls()
    #         builder.dump_dependencies_content_checksum(
    #             content_checksum_path=cache_args.content_checksum_path
    #         )
    #         exit(0)
    #
    #     if cache_args.cache_dependencies_path:
    #         builder = cls()
    #         builder.prepare_dependencies(
    #             cache_dir=cache_args.cache_dependencies_path,
    #         )
    #         exit(0)
    #
    #     build_parser = argparse.ArgumentParser()
    #
    #     build_parser.add_argument(
    #         "--cache-dir", type=str, dest="cache_dir",
    #         help="The directory where the build dependencies has to be cached. This should be mostly "
    #              "used by CI/CD to reduce the build time."
    #     )
    #
    #     build_parser.add_argument(
    #         "--output-dir", required=True, type=str, dest="output_dir",
    #         help="The directory where the result package has to be stored."
    #     )
    #     build_parser.add_argument(
    #         "--locally", action="store_true",
    #         help="Some of the packages by default are build inside the docker to provide consistent build environment."
    #              "Inside the docker this script is executed once more, but with the '--locally' option, "
    #              "so it's aware that it should build the package directly in the docker."
    #     )
    #
    #     build_parser.add_argument(
    #         "--no-versioned-file-name",
    #         action="store_true",
    #         dest="no_versioned_file_name",
    #         default=False,
    #         help="If true, will not embed the version number in the artifact's file name.  This only "
    #              "applies to the `tarball` and container builders artifacts.",
    #     )
    #
    #     build_args = build_parser.parse_args(args=build_argv)
    #
    #     build_info = common.PackageBuildInfo(
    #         build_summary=common.get_build_info(),
    #         no_versioned_file_name=build_args.no_versioned_file_name
    #     )
    #
    #     output_path = pl.Path(build_args.output_dir)
    #     output_path.mkdir(exist_ok=True, parents=True)
    #
    #     builder = cls(
    #         cache_dir=build_args.cache_dir,
    #         locally=build_args.locally,
    #     )
    #
    #     builder.build(
    #         build_info=build_info,
    #         output_path=output_path,
    #     )


