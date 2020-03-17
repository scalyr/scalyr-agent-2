from __future__ import unicode_literals
from __future__ import print_function

import pytest

from tests.distribution_builders.ubuntu import UbuntuBuilder


from tests.utils.dockerized import dockerized_case
from tests.distribution.python_version_change_tests.common import (
    common_test_python2,
    common_test_python3,
    common_test_python2to3,
)
from tests.common import install_deb


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python3():
    common_test_python3(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python2():
    common_test_python2(install_deb)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(UbuntuBuilder, __file__)
def test_deb_python2to3():
    common_test_python2to3(install_deb)