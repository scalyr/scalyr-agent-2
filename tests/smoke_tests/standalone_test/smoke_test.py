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

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import


import sys

import pytest

from scalyr_agent import __scalyr__
from tests.smoke_tests.common import _test_standalone_smoke


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_smoke():
    _test_standalone_smoke(__scalyr__.InstallType.DEV_INSTALL)


@pytest.mark.skipif(
    sys.version_info < (2, 7), reason="Skip multiprocess configuration for python 2.6"
)
@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_smoke_with_process_workers():
    _test_standalone_smoke(
        __scalyr__.InstallType.DEV_INSTALL, workers_type="process", workers_sessions_count=2
    )
