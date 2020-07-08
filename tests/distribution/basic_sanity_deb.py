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
Basic sanity tests for Debian based distros.
"""

from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import

import time

import pytest

from tests.common import install_deb
from tests.utils.dockerized import dockerized_case
from tests.utils.agent_runner import AgentRunner
from tests.utils.agent_runner import PACKAGE_INSTALL
from tests.image_builder.distributions.ubuntu import UbuntuBuilder


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(
    UbuntuBuilder, __file__,
)
def test_default_compression_algorithm(request):
    runner = AgentRunner(PACKAGE_INSTALL, send_to_server=False)

    # deflate is the default
    install_deb()

    runner.start()
    time.sleep(1)

    agent_status = runner.status_json(True)
    compression_algorithm = agent_status["compression_algorithm"]
    compression_level = agent_status["compression_algorithm"]

    assert compression_algorithm == "deflate", "expected deflate, got %s" % (
        compression_algorithm
    )
    assert compression_level == 6

    runner.stop()
