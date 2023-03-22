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
import logging
import tarfile

import pytest

from agent_build_refactored.tools.constants import Architecture
from tests.end_to_end_tests.run_in_remote_machine import run_test_remotely
from tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner import (
    PORTABLE_PYTEST_RUNNER_BUILDERS,
)


logger = logging.getLogger(__name__)


def test_remotely(
    target_distro,
    remote_machine_type,
    package_builder_name,
    package_builder,
    server_root,
    scalyr_api_key,
    scalyr_api_read_key,
    scalyr_server,
    test_session_suffix,
    tmp_path,
    use_aio_package
):

    if use_aio_package:
        arch = package_builder.DEPENDENCY_PACKAGES_ARCHITECTURE
    else:
        arch = Architecture.X86_64

    pytest_runner_builder_cls = PORTABLE_PYTEST_RUNNER_BUILDERS[arch]
    pytest_runner_builder = pytest_runner_builder_cls()
    pytest_runner_builder.build()

    packages_archive_path = tmp_path / "packages.tar"
    with tarfile.open(packages_archive_path, "w") as tf:
        tf.add(server_root, arcname="/")

    try:
        run_test_remotely(
            target_distro=target_distro,
            remote_machine_type=remote_machine_type,
            command=[
                "tests/end_to_end_tests/managed_packages_tests",
                "--builder-name",
                package_builder_name,
                "--distro-name",
                target_distro.name,
                "--remote-machine-type",
                remote_machine_type,
                "--runs-locally",
                "--packages-source-type",
                "repo-tarball",
                "--packages-source",
                "/tmp/packages.tar",
                "--scalyr-api-key",
                scalyr_api_key,
                "--scalyr-api-read-key",
                scalyr_api_read_key,
                "--scalyr-server",
                scalyr_server,
                "--test-session-suffix",
                test_session_suffix,
            ],
            architecture=arch,
            pytest_runner_path=pytest_runner_builder.result_runner_path,
            file_mappings={str(packages_archive_path): "/tmp/packages.tar"},
        )
    except Exception as e:
        logger.error(f"Remote test failed. Error: {str(e)}")
        pytest.exit(1)
