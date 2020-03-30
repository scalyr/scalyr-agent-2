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

from tests.distribution_builders.centos7 import CentOSBuilder

from tests.utils.dockerized import dockerized_case
from tests.distribution.python_version_change_tests.common import (
    common_test_switch_command_works_without_agent_config,
    common_test_python2,
    common_test_python3,
    common_test_only_python_mapped_to_python2,
    common_test_only_python_mapped_to_python3,
    common_test_no_python,
    common_test_switch_default_to_python2,
    common_test_switch_default_to_python3,
    common_test_switch_python2_to_python3,
    common_version_test,
)
from tests.common import install_rpm, install_next_version_rpm, remove_rpm
from tests.utils.agent_runner import AgentRunner, PACKAGE_INSTALL


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CentOSBuilder, __file__, python_executable="python_for_tests")
def test_centos_no_python(request):
    common_test_no_python(install_rpm)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CentOSBuilder, __file__, python_executable="python_for_tests")
def test_centos_only_python_mapped_to_python2(request):
    common_test_only_python_mapped_to_python2(install_rpm, install_next_version_rpm)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(30)
@dockerized_case(CentOSBuilder, __file__, python_executable="python_for_tests")
def test_centos_python2(request):
    common_test_python2(install_rpm, install_next_version_rpm)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CentOSBuilder, __file__, python_executable="python_for_tests")
def test_centos_switch_default_to_python2(request):
    common_test_switch_default_to_python2(install_rpm, install_next_version_rpm)
