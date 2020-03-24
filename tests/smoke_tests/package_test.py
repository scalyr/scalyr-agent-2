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

from tests.smoke_tests.common import _test_standalone_smoke
from tests.utils.agent_runner import PACKAGE_INSTALL

from tests.utils.dockerized import dockerized_case
from tests.distribution_builders.amazonlinux import AmazonlinuxBuilder
from tests.distribution_builders.ubuntu import UbuntuBuilder
from tests.common import install_rpm, install_deb


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_smoke_package_rpm_python2(request):
    install_rpm()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_smoke_package_rpm_python3(request):
    install_rpm()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python3")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(UbuntuBuilder, __file__)
def test_smoke_package_deb_python2(request):
    install_deb()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(UbuntuBuilder, __file__)
def test_smoke_package_deb_python3(request):
    install_deb()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python3")
