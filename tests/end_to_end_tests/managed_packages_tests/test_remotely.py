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
THis special test module is responsible for running the 'managed_packages' tests in remote environment,
for example ec2 intsance or docker container.
"""

import os
import tarfile

import pytest

from agent_build_refactored.tools.constants import DockerPlatform, Architecture
from tests.end_to_end_tests.run_in_remote_machine import run_test_remotely, DISTROS
from tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner import PortablePytestRunnerBuilder

RUNS_REMOTELY = bool(os.environ.get("TEST_RUNS_REMOTELY"))


@pytest.mark.skipif(RUNS_REMOTELY, reason="Should be skipped when already runs in a remote machine.")
def test_remotely(distro, repo_dir, package_builder_name, package_builder, tmp_path, request):

    pytest_runner_builder = PortablePytestRunnerBuilder()
    pytest_runner_builder.build()

    repo_dir_archive_path = tmp_path / "repo_dir.tar"
    with tarfile.open(repo_dir_archive_path, "w") as tf:
        tf.add(repo_dir, arcname="/")

    run_test_remotely(
        remote_distro_name=distro,
        command=[
            "tests/end_to_end_tests/managed_packages_tests",
            "--builder-name",
            package_builder_name,
            "--distro",
            distro,
            "--packages-source-type",
            "repo",
            "--packages-source",
            "/tmp/repo-dir",
        ],
        architecture=package_builder.ARCHITECTURE,
        pytest_runner_path=pytest_runner_builder.result_runner_path,
        test_options=request.config.option,
        file_mappings={
            str(repo_dir_archive_path): "/tmp/repo-dir"
        },
    )