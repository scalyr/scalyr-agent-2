from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import os
import time

from scalyr_agent import compat
from scalyr_agent.__scalyr__ import DEV_INSTALL, get_package_root
from tests.smoke_tests.verifier import (
    AgentLogVerifier,
    DataJsonVerifier,
    SystemMetricsVerifier,
    ProcessMetricsVerifier,
)
from tests.utils.agent_runner import AgentRunner


def _test_standalone_smoke(agent_installation_type, python_version=None):
    """
    Agent standalone test to run within the same machine.
    """
    if agent_installation_type == DEV_INSTALL:
        os.chdir(get_package_root())

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
