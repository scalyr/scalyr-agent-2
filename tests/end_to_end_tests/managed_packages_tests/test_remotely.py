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

import os
import tarfile

import pytest

from tests.end_to_end_tests.run_in_remote_machine import run_test_remotely
from tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner import PortablePytestRunnerBuilder

# Special environment variable flag that indicates that test case is already running inside remote machine,
# so we have to skip remote execution to avoid loop.
RUNS_REMOTELY = bool(os.environ.get("TEST_RUNS_REMOTELY"))


@pytest.mark.skipif(RUNS_REMOTELY, reason="Should be skipped when already runs in a remote machine.")
def test_remotely(
        distro_name,
        remote_machine_type,
        package_builder_name,
        package_builder,
        package_source_type,
        package_source,
        scalyr_api_key,
        scalyr_api_read_key,
        scalyr_server,
        test_session_suffix,
        tmp_path,
        request
):

    pytest_runner_builder = PortablePytestRunnerBuilder()
    pytest_runner_builder.build()

    packages_archive_path = tmp_path / "packages.tar"
    with tarfile.open(packages_archive_path, "w") as tf:
        tf.add(package_source, arcname="/")

    run_test_remotely(
        distro_name=distro_name,
        remote_machine_type=remote_machine_type,
        command=[
            "tests/end_to_end_tests/managed_packages_tests",
            "--builder-name",
            package_builder_name,
            "--distro",
            request.config.option.distro,
            "--packages-source-type",
            package_source_type,
            "--packages-source",
            "/tmp/packages",
            "--scalyr-api-key",
            scalyr_api_key,
            "--scalyr-api-read-key",
            scalyr_api_read_key,
            "--scalyr-server",
            scalyr_server,
            "--test-session-suffix",
            test_session_suffix,
        ],
        architecture=package_builder.ARCHITECTURE,
        pytest_runner_path=pytest_runner_builder.result_runner_path,
        test_options=request.config.option,
        file_mappings={
            str(packages_archive_path): "/tmp/packages"
        },
    )