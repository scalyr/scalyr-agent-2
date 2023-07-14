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

"""
This special test module is responsible for running the 'managed_packages' tests in a remote environment,
for example ec2 instance or docker container.
"""
import argparse
import pathlib as pl
import logging
import shutil
import sys
import tarfile
from typing import List, Type, Dict, Optional

sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.builder import Builder
from agent_build_refactored.managed_packages.managed_packages_builders import (
    get_package_builder_by_name,
    LinuxAIOPackagesBuilder,
    ALL_PACKAGE_BUILDERS,
    ALL_AIO_PACKAGE_BUILDERS,
    PORTABLE_PYTEST_RUNNER_NAME,
)
from agent_build_refactored.tools.constants import CpuArch, LibC, SOURCE_ROOT
from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.tools.docker.buildx.build import LocalDirectoryBuildOutput, buildx_build
from tests.end_to_end_tests.run_in_remote_machine import run_test_remotely

from tests.end_to_end_tests.run_in_remote_machine import DISTROS

from tests.end_to_end_tests.managed_packages_tests.remote_machine_tests.tools import (
    create_packages_repo_root,
    get_packages_stable_version,
    is_builder_creates_aio_package
)
from tests.end_to_end_tests.managed_packages_tests.remote_machine_tests.conftest import add_cmd_args
from tests.end_to_end_tests.run_in_remote_machine.prepare_agent_source import (
    prepare_agent_source_tarball,
    AGENT_SOURCE_TARBALL_FILENAME,
)

init_logging()

logger = logging.getLogger(__name__)

PACKAGES_ROOT_TARBALL_NAME = "packages_repo_root.tar"


class RemoteTestDependenciesBuilder(Builder):
    PACKAGE_BUILDER: Type[LinuxAIOPackagesBuilder]

    def __init__(
        self,
        package_type: str,
        packages_source_type: str,
        packages_source: str,
        package_builder_name: str
    ):

        super(RemoteTestDependenciesBuilder, self).__init__()

        self.package_type = package_type
        self.packages_source_type = packages_source_type
        self.packages_source = packages_source
        self.package_builder_name = package_builder_name

    @property
    def portable_pytest_runner_path(self):
        return self.result_dir / PORTABLE_PYTEST_RUNNER_NAME

    @property
    def agent_source_tarball_path(self) -> pl.Path:
        return self.result_dir / AGENT_SOURCE_TARBALL_FILENAME

    def _build(self):

        is_aio = is_builder_creates_aio_package(
            package_builder_name=self.package_builder_name
        )

        if is_aio:
            aio_builder = self.__class__.PACKAGE_BUILDER
        else:
            aio_builder = ALL_PACKAGE_BUILDERS["aio-x86_64"]

        python_dependency_dir = self.work_dir / "python_dependency"
        aio_builder.build_dependencies(
            output=LocalDirectoryBuildOutput(
                dest=python_dependency_dir,
            )
        )
        shutil.copy(
            python_dependency_dir / PORTABLE_PYTEST_RUNNER_NAME,
            self.result_dir,
        )

        prepare_agent_source_tarball(
            output_dir=self.result_dir
        )

        stable_version_package_version = get_packages_stable_version()
        packages_root = create_packages_repo_root(
            packages_source_type=self.packages_source_type,
            packages_source=self.packages_source,
            package_builder=self.__class__.PACKAGE_BUILDER,
            package_type=self.package_type,
            stable_packages_version=stable_version_package_version,
            output_dir=self.work_dir,
        )

        packages_root_tarball_path = self.result_dir / PACKAGES_ROOT_TARBALL_NAME
        with tarfile.open(packages_root_tarball_path, "w") as tf:
            tf.add(packages_root, arcname="/")


remote_test_dependency_builders: Dict[str, Type[RemoteTestDependenciesBuilder]] = {}

for package_builder in ALL_PACKAGE_BUILDERS.values():
    class _RemoteTestDependenciesBuilder(RemoteTestDependenciesBuilder):
        NAME = "remote_test_dependency_builder"
        PACKAGE_BUILDER = package_builder

    remote_test_dependency_builders[package_builder.NAME] = _RemoteTestDependenciesBuilder


def main(
    package_type: str,
    packages_source_type: str,
    packages_source: str,
    distro_name,
    remote_machine_type,
    package_builder_name,
    test_path: str,
    other_cmd_args: List[str],
):

    use_aio_package = is_builder_creates_aio_package(
        package_builder_name=package_builder_name
    )

    dependencies_builder_cls = remote_test_dependency_builders[package_builder_name]
    if use_aio_package:
        arch = dependencies_builder_cls.PACKAGE_BUILDER.ARCHITECTURE
    else:
        arch = CpuArch.x86_64

    dependencies_builder = dependencies_builder_cls(
        package_type=package_type,
        packages_source_type=packages_source_type,
        packages_source=packages_source,
        package_builder_name=package_builder_name,
    )

    dependencies_builder.build()

    distro = DISTROS[distro_name]

    packages_root_tarball = dependencies_builder.result_dir / PACKAGES_ROOT_TARBALL_NAME
    in_docker_packages_root_tarball = f"/tmp/{PACKAGES_ROOT_TARBALL_NAME}"

    try:
        run_test_remotely(
            target_distro=distro,
            remote_machine_type=remote_machine_type,

            command=[
                "tests/end_to_end_tests/managed_packages_tests/remote_machine_tests",
                "--builder-name",
                package_builder_name,
                "--package-type",
                package_type,
                "--distro-name",
                distro_name,
                "--remote-machine-type",
                remote_machine_type,
                "--packages-source-type",
                "repo-tarball",
                "--packages-source",
                in_docker_packages_root_tarball,
                *other_cmd_args,
            ],
            architecture=arch,
            pytest_runner_path=dependencies_builder.portable_pytest_runner_path,
            source_tarball_path=dependencies_builder.agent_source_tarball_path,
            file_mappings={
                packages_root_tarball: in_docker_packages_root_tarball
            },
        )
    except Exception as e:
        logger.error(f"Remote test failed. Error: {str(e)}")
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    add_cmd_args(parser=parser, is_pytest_parser=False)

    parser.add_argument("test_path")

    args, other_argv = parser.parse_known_args()

    main(
        package_type=args.package_type,
        packages_source_type=args.packages_source_type,
        packages_source=args.packages_source,
        distro_name=args.distro_name,
        remote_machine_type=args.remote_machine_type,
        package_builder_name=args.builder_name,
        test_path=args.test_path,
        other_cmd_args=other_argv,
    )