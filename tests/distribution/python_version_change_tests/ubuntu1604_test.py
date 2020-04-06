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

from tests.distribution_builders.ubuntu1604 import UbuntuBuilder

from tests.utils.dockerized import dockerized_case
from tests.distribution.python_version_change_tests.common import (
    common_test_python2,
    common_test_only_python_mapped_to_python2,
    common_test_no_python,
    common_test_switch_default_to_python2,
    common_version_test,
)
from tests.common import install_deb, install_next_version_deb, remove_deb
from tests.utils.agent_runner import PACKAGE_INSTALL, AgentRunner


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__, python_executable="python_for_tests")
def test_ubuntu_test_versions(request):
    runner = AgentRunner(PACKAGE_INSTALL)
    common_version_test(
        runner,
        install_deb,
        remove_deb,
        None,
        "2.5.1",
        "2.5.1",
        "3.4.1",
        install_fails=True,
    )

    common_version_test(
        runner, install_deb, remove_deb, "config_main_py2.py", "2.5.1", "", ""
    )
    common_version_test(
        runner, install_deb, remove_deb, "config_main_py2.py", "2.5.1", "", ""
    )

    common_version_test(runner, install_deb, remove_deb, "config_main.py", "", "", "")

    common_version_test(
        runner, install_deb, remove_deb, "config_main.py", "", "2.5.1", ""
    )


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__, python_executable="python_for_tests")
def test_ubuntu_no_python(request):
    common_test_no_python(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__, python_executable="python_for_tests")
def test_ubuntu_only_python_mapped_to_python2(request):
    common_test_only_python_mapped_to_python2(install_deb, install_next_version_deb)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(30)
@dockerized_case(UbuntuBuilder, __file__, python_executable="python_for_tests")
def test_ubuntu_python2(request):
    common_test_python2(install_deb, install_next_version_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__, python_executable="python_for_tests")
def test_ubuntu_switch_default_to_python2(request):
    common_test_switch_default_to_python2(install_deb, install_next_version_deb)
