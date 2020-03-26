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

from tests.images_builder.distribution_builders import UbuntuBuilder

from tests.utils.dockerized import dockerized_case
from tests.distribution.python_version_change_tests.common import (
    common_test_python2,
    common_test_python3,
    common_test_python2to3,
    common_test_python3_upgrade,
)
from tests.common import install_deb, install_next_version_deb


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python3(request):
    common_test_python3(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python2(request):
    common_test_python2(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python2to3(request):
    common_test_python2to3(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python3_upgrade(request):
    common_test_python3_upgrade(install_deb, install_next_version_deb)
