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
import sys
import tarfile
from typing import List, Type, Dict

sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent.parent))

from agent_build_refactored.managed_packages.managed_packages_builders import (
    LinuxAIOPackagesBuilder,
    ALL_PACKAGE_BUILDERS,
)
from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.common import init_logging
from tests.end_to_end_tests.run_in_remote_machine import (
    run_test_in_docker,
    run_tests_in_ec2,
)

from tests.end_to_end_tests.run_in_remote_machine import DISTROS

from tests.end_to_end_tests.managed_packages_tests.remote_machine_tests.tools import (
    create_packages_repo_root,
    get_packages_stable_version,
    is_builder_creates_aio_package,
)
from tests.end_to_end_tests.managed_packages_tests.remote_machine_tests.conftest import (
    add_cmd_args,
)
from tests.end_to_end_tests.run_in_remote_machine import RemoteTestDependenciesBuilder

init_logging()

logger = logging.getLogger(__name__)

PACKAGES_ROOT_TARBALL_NAME = "packages_repo_root.tar"


class RemotePackageTestDependenciesBuilder(RemoteTestDependenciesBuilder):
    PACKAGE_BUILDER: Type[LinuxAIOPackagesBuilder]

    def __init__(
        self,
        package_type: str,
        packages_source_type: str,
        packages_source: str,
        package_builder_name: str,
    ):

        super(RemoteTestDependenciesBuilder, self).__init__()

        self.package_type = package_type
        self.packages_source_type = packages_source_type
        self.packages_source = packages_source
        self.package_builder_name = package_builder_name

    def build(self):

        is_aio = is_builder_creates_aio_package(
            package_builder_name=self.package_builder_name
        )

        if is_aio:
            # If it's already AIO package, then just use itself
            dependencies_arch = self.__class__.PACKAGE_BUILDER.ARCHITECTURE
        else:
            # If it's non-aio, then we use x86_64 builder.
            dependencies_arch = CpuArch.x86_64

        self._build_dependencies(
            architecture=dependencies_arch,
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


remote_test_dependency_builders: Dict[
    str, Type[RemotePackageTestDependenciesBuilder]
] = {}

for package_builder in ALL_PACKAGE_BUILDERS.values():

    class _RemotePackageTestDependenciesBuilder(RemotePackageTestDependenciesBuilder):
        NAME = "remote_test_dependency_builder"
        PACKAGE_BUILDER = package_builder

    remote_test_dependency_builders[package_builder.NAME] = (
        _RemotePackageTestDependenciesBuilder
    )


def main(
    package_type: str,
    packages_source_type: str,
    packages_source: str,
    distro_name,
    remote_machine_type,
    package_builder_name,
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

    command = [
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
    ]

    try:
        if remote_machine_type == "ec2":

            run_tests_in_ec2(
                ec2_image=distro.ec2_images[arch],
                ec2_instance_size_id=distro.ec2_instance_size_id,
                command=command,
                pytest_runner_path=dependencies_builder.portable_pytest_runner_path,
                source_tarball_path=dependencies_builder.agent_source_tarball_path,
                file_mappings={
                    packages_root_tarball: in_docker_packages_root_tarball,
                },
            )
        else:
            run_test_in_docker(
                docker_image=distro.docker_image,
                command=command,
                architecture=arch,
                pytest_runner_path=dependencies_builder.portable_pytest_runner_path,
                source_tarball_path=dependencies_builder.agent_source_tarball_path,
                file_mappings={
                    packages_root_tarball: in_docker_packages_root_tarball,
                },
            )
    except Exception as e:
        logger.error(f"Remote test failed. Error: {str(e)}")
        raise


if __name__ == "__main__":
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
        other_cmd_args=other_argv,
    )
