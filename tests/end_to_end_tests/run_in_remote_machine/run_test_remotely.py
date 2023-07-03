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
import logging
import tarfile
from typing import List

import pytest

from agent_build_refactored.managed_packages.managed_packages_builders import get_package_builder_by_name
from agent_build_refactored.tools.constants import CpuArch, LibC, SOURCE_ROOT
from tests.end_to_end_tests.run_in_remote_machine import run_test_remotely
from tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner import (
    PORTABLE_PYTEST_RUNNER_BUILDER_STEPS
)
from tests.end_to_end_tests.run_in_remote_machine import DISTROS

from tests.end_to_end_tests.managed_packages_tests.tools import create_server_root, get_packages_stable_version, \
    WORK_DIR, is_builder_creates_aio_package
from tests.end_to_end_tests.managed_packages_tests.conftest import add_cmd_args

logger = logging.getLogger(__name__)


def main(
    packages_source_type: str,
    packages_source: str,
    distro_name,
    remote_machine_type,
    package_builder_name,
    other_cmd_args: List[str],
):

    package_builder = get_package_builder_by_name(
        name=package_builder_name,
    )

    stable_version_package_version = get_packages_stable_version()
    server_root = create_server_root(
        packages_source_type=packages_source_type,
        packages_source=packages_source,
        package_builder=package_builder,
        stable_packages_version=stable_version_package_version,
    )

    use_aio_package =  is_builder_creates_aio_package(
        package_builder_name=package_builder_name
    )

    if use_aio_package:
        arch = package_builder.ARCHITECTURE
        libc = package_builder.LIBC
    else:
        arch = CpuArch.x86_64
        libc = LibC.GNU

    pytest_runner_builder = PORTABLE_PYTEST_RUNNER_BUILDER_STEPS[libc][arch]
    pytest_runner_builder.run_and_output_in_local_directory(
        output_dir=WORK_DIR
    )

    packages_archive_path = WORK_DIR / "packages.tar"
    with tarfile.open(packages_archive_path, "w") as tf:
        tf.add(server_root, arcname="/")

    distro = DISTROS[distro_name]

    try:
        run_test_remotely(
            target_distro=distro,
            remote_machine_type=remote_machine_type,
            command=[
                "tests/end_to_end_tests/managed_packages_tests",
                "--builder-name",
                package_builder_name,
                "--distro-name",
                distro_name,
                "--remote-machine-type",
                remote_machine_type,
                "--packages-source-type",
                "repo-tarball",
                "--packages-source",
                "/tmp/packages.tar",
                *other_cmd_args,
            ],
            architecture=arch,
            pytest_runner_path=WORK_DIR / pytest_runner_builder.__class__.PORTABLE_RUNNER_NAME,
            file_mappings={str(packages_archive_path): "/tmp/packages.tar"},
        )
    except Exception as e:
        logger.error(f"Remote test failed. Error: {str(e)}")
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    add_cmd_args(parser=parser, is_pytest_parser=False)

    args, other_argv = parser.parse_known_args()

    main(
        packages_source_type=args.packages_source_type,
        packages_source=args.packages_source,
        distro_name=args.distro_name,
        remote_machine_type=args.remote_machine_type,
        package_builder_name=args.builder_name,
        other_cmd_args=other_argv,
    )