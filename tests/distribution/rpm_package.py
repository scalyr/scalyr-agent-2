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

import pytest

from tests.utils.dockerized import dockerized_case
from tests.image_builder.distributions.centos8 import CentOSBuilder


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(
    CentOSBuilder,
    __file__,
    file_paths_to_copy=["/scalyr-agent.rpm"],
    artifacts_use_subdirectory=False,
)
def test_build_rpm_package(request):
    """
    Mock function which is used to build agent rpm package.
    """
    pass
