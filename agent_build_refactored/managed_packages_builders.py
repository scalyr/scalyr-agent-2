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


import datetime
import shutil
import tarfile
import argparse
import os
import pathlib as pl
from typing import List

from agent_build_refactored.tools.runner import Runner, RunnerStep, ArtifactRunnerStep
from agent_build_refactored.tools.constants import SOURCE_ROOT, EMBEDDED_PYTHON_VERSION
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import build_linux_lfs_agent_files
from agent_build_refactored.tools.build_python.build_python import BUILD_PYTHON_GLIBC_X86_64
from agent_build_refactored.managed_packages.dependency_packages import BUILD_PYTHON_PACKAGE_GLIBC_X86_64, BUILD_AGENT_PYTHON_DEPENDENCIES_PACKAGE_GLIBC_X86_64


class PythonPackageBuilder(Runner):
    PACKAGE_TYPE: str
    PACKAGE_ARCHITECTURE: str
    BUILD_PYTHON_STEP: ArtifactRunnerStep
    BUILD_AGENT_PYTHON_DEPENDENCIES_STEP: ArtifactRunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        steps = super(PythonPackageBuilder, cls).get_all_required_steps()

        steps.extend([
            cls.BUILD_PYTHON_STEP,
            cls.BUILD_AGENT_PYTHON_DEPENDENCIES_STEP
        ])
        return steps

    def run(self):
        #super(PythonPackageBuilder, self).run()
        self.build_packages()

    @property
    def packages_output_path(self) -> pl.Path:
        return self.output_path / "packages"

    def build_agent_package(
            self,
            agent_dependencies_version: str,
            version=None
    ):
        pass

    def build_packages(
            self,
            build_for: str = None,
            version: str = None
    ):

        super(PythonPackageBuilder, self).run_required()

        if not version:
            version_file_path = SOURCE_ROOT / "VERSION"
            version = version_file_path.read_text().strip()

        agent_package_root_path = self.output_path / "agent_package_root"
        build_linux_lfs_agent_files(
            output_path=agent_package_root_path,
            version=version,
            copy_agent_source=True
        )

        package_etc_dir = agent_package_root_path / "etc"
        package_etc_dir.mkdir(parents=True)
        shutil.copytree(
            SOURCE_ROOT / "config",
            package_etc_dir / "scalyr-agent-2",
        )

        agent_d_path = agent_package_root_path / "etc/scalyr-agent-2/agent.d"
        agent_d_path.mkdir(parents=True)
        os.chmod(agent_d_path, int("741", 8))

        shutil.copytree(
            SOURCE_ROOT / "agent_build/linux/managed_packages/files/init.d",
            agent_package_root_path / "etc/init.d"
        )


        # shutil.copy2(
        #     SOURCE_ROOT / "agent_build/linux/managed_packages/scalyr-agent-2",
        #     agent_package_root_path / "usr/share/scalyr-agent-2/bin/scalyr-agent-2"
        # )

        description = "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics " \
                      "and log files and transmit them to Scalyr."

        scriptlets_path = SOURCE_ROOT / "installer/new_scripts"

        check_call_with_log(
            [
                # fmt: off
                "fpm",
                "-s", "dir",
                "-a", type(self).PACKAGE_ARCHITECTURE,
                "-t", type(self).PACKAGE_TYPE,
                "-n", "scalyr-agent-2",
                "-v", version,
                "-C", str(agent_package_root_path),
                "--license", '"Apache 2.0"',
                "--vendor", "Scalyr %s",
                "--provides", "scalyr-agent-2",
                "--description", description,
                "--depends", "bash >= 3.2",
                "--depends", f"{agent_dependencies_package_name} = {agent_dependencies_package_version}",
                "--url", "https://www.scalyr.com",
                "--deb-user", "root",
                "--deb-group", "root",
                # "--deb-changelog", "changelog-deb",
                "--rpm-user", "root",
                "--rpm-group", "root",
                #"--rpm-changelog", "changelog-rpm",
                "--before-install", str(scriptlets_path / "preinstall.sh"),
                "--after-install", str(scriptlets_path / "postinstall.sh"),
                "--before-remove", str(scriptlets_path / "preuninstall.sh"),
                "--deb-no-default-config-files",
                "--no-deb-auto-config-files",
                "--config-files", "/etc/scalyr-agent-2/agent.json",
                # NOTE: We leave those two files in place since they are symlinks which might have been
                # updated by scalyr-switch-python and we want to leave this in place - aka make sure
                # selected Python version is preserved on upgrade
                "--config-files", "/usr/share/scalyr-agent-2/bin/scalyr-agent-2",
                # "  --config-files /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config "
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
                # fmt: on
            ],
            cwd=str(self.packages_output_path)
        )

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(PythonPackageBuilder, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command", required=True)

        build_packages_parser = subparsers.add_parser("build_packages")

        build_packages_parser.add_argument(
            "--output-dir",
            dest="output_dir",
            required=True
        )

        build_packages_parser.add_argument(
            "--build-for",
            dest="build_for"
        )

        build_packages_parser.add_argument(
            "--version",
            dest="version",
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(PythonPackageBuilder, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "build_packages":
            builder.build_packages()

            output_path = pl.Path(args.output_dir)
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.copytree(
                builder.output_path,
                args.output_dir
            )


class DebPythonPackageBuilderX64(PythonPackageBuilder):
    PACKAGE_ARCHITECTURE = "amd64"
    PACKAGE_TYPE = "deb"
    BUILD_PYTHON_STEP = BUILD_PYTHON_PACKAGE_GLIBC_X86_64
    BUILD_AGENT_PYTHON_DEPENDENCIES_STEP = BUILD_AGENT_PYTHON_DEPENDENCIES_PACKAGE_GLIBC_X86_64


MANAGED_PACKAGE_BUILDERS = {
    "deb-x64": DebPythonPackageBuilderX64
}