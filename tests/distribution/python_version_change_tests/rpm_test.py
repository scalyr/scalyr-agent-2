from __future__ import unicode_literals
from __future__ import print_function

import pytest

from tests.distribution_builders.amazonlinux import AmazonlinuxBuilder

from tests.utils.dockerized import dockerized_case
from tests.distribution.python_version_change_tests.common import (
    common_test_python2,
    common_test_python3,
    common_test_python2to3,
    common_test_python3_upgrade
)
from tests.common import install_rpm


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_rpm_python3():
    common_test_python3(install_rpm)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_rpm_python2():
    common_test_python2(install_rpm)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_rpm_python2to3():
    common_test_python2to3(install_rpm)


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_rpm_python3_upgrade():
    common_test_python3_upgrade(install_rpm)
