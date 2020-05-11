# Copyright 2014-2020 Scalyr Inc.
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
Basic sanity tests for RedHat / CentOS based distros.
"""

from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import

import time

import pytest

from tests.common import install_rpm
from tests.common import run_command
from tests.utils.dockerized import dockerized_case
from tests.utils.agent_runner import AgentRunner
from tests.utils.agent_runner import PACKAGE_INSTALL
from tests.image_builder.distributions.centos8 import CentOSBuilder


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(
    CentOSBuilder, __file__,
)
def test_default_compression_algorithm(request):
    """
    Ensure that zstandard is used by default if corresponding package is available and deflate is
    used as a fallback.
    """
    runner = AgentRunner(PACKAGE_INSTALL, send_to_server=False)

    # 1. zstandard not available, should use deflate
    run_command("python2 -m pip uninstall zstandard || true")

    install_rpm()

    runner.start()
    time.sleep(1)

    agent_status = runner.status_json(True)
    compression_algorithm = agent_status["compression_algorithm"]

    assert compression_algorithm == "deflate", "expected deflate, got %s" % (
        compression_algorithm
    )

    # 2. zstandard available, should default to that
    exit_code, _, _ = run_command("python2 -m pip install zstandard")

    assert exit_code == 0, "Failed to install zstandard pip package"

    runner.restart()
    time.sleep(1)

    agent_status = runner.status_json(True)
    compression_algorithm = agent_status["compression_algorithm"]

    assert compression_algorithm == "zstandard", "expected zstandard, got %s" % (
        compression_algorithm
    )

    runner.stop()
