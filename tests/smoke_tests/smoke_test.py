import time

import pytest

from scalyr_agent import compat
from tests.utils.agent_runner import AgentRunner, DEV_INSTALL, PACKAGE_INSTALL
from tests.smoke_tests.verifier import (
    AgentLogVerifier,
    DataJsonVerifier,
    SystemMetricsVerifier,
    ProcessMetricsVerifier
)

from tests.utils.dockerized import  dockerized_case
from tests.distribution_builders.amazonlinux import AmazonlinuxBuilder
from tests.distribution_builders.ubuntu import UbuntuBuilder
from tests.common import install_rpm, install_deb


def _test_standalone_smoke(agent_installation_type, python_version=None):
    """
    Agent standalone test to run within the same machine.
    """

    print("")
    print("Agent host name: {0}".format(compat.os_environ_unicode["AGENT_HOST_NAME"]))

    runner = AgentRunner(agent_installation_type)
    if python_version:
        runner.switch_version(python_version)

    agent_log_verifier = AgentLogVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )
    data_json_verifier = DataJsonVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )
    system_metrics_verifier = SystemMetricsVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )
    process_metrics_verifier = ProcessMetricsVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )

    runner.start()

    time.sleep(1)

    print("Verify 'agent.log'")
    assert agent_log_verifier.verify(), "Verification of the file: 'agent.log' failed"
    print("Verify 'linux_system_metrics.log'")
    assert (
        system_metrics_verifier.verify()
    ), "Verification of the file: 'linux_system_metrics.log' failed"
    print("Verify 'linux_process_metrics.log'")
    assert (
        process_metrics_verifier.verify()
    ), "Verification of the file: 'linux_process_metrics.log' failed"

    assert data_json_verifier.verify(), "Verification of the file: 'data.json' failed"

    runner.stop()


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_smoke():
    _test_standalone_smoke(DEV_INSTALL)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_smoke_package_rpm_python2():
    install_rpm()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(AmazonlinuxBuilder, __file__)
def test_smoke_package_rpm_python3():
    install_rpm()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python3")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(UbuntuBuilder, __file__)
def test_smoke_package_deb_python2():
    install_deb()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
@dockerized_case(UbuntuBuilder, __file__)
def test_smoke_package_deb_python3():
    install_deb()
    _test_standalone_smoke(PACKAGE_INSTALL, python_version="python3")