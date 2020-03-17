from __future__ import print_function
from __future__ import absolute_import

import os
import time
import json

from tests.utils.compat import Path
from tests.utils.agent_runner import AgentRunner, PACKAGE_INSTALL


def _check_version(runner, major_version):
    status = json.loads(runner.status_json())

    version_string = status["python_version"]

    version = int(version_string[0])

    print(runner.status())
    assert version == major_version


def common_test_python3(install_package_fn):
    print("")
    os.remove(str(Path("/", "usr", "bin", "python")))
    os.remove(str(Path("/", "usr", "bin", "python2")))

    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(5)

    status = json.loads(runner.status_json())

    python_version = status["python_version"]

    print(runner.status())

    assert python_version.startswith("3.")


def common_test_python2(install_package_fn):
    print("")
    os.remove(str(Path("/", "usr", "bin", "python3")))

    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()

    time.sleep(5)

    status = json.loads(runner.status_json())

    python_version = status["python_version"]

    print(runner.status())

    assert python_version.startswith("2.")


def common_test_python2to3(install_package_fn):
    print("")

    print("Check default python2.")
    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)

    runner.start()

    time.sleep(5)

    status = json.loads(runner.status_json())

    python_version = status["python_version"]
    print("Agent status: ")
    print(runner.status())
    assert python_version.startswith("2.")

    runner.stop()

    runner.switch_version("python3")

    runner.start()

    time.sleep(5)

    status = json.loads(runner.status_json())

    python_version = status["python_version"]

    assert python_version.startswith("3.")

def install_next_version():
    import subprocess
    subprocess.check_call(
        "rpm -U /scalyr-agent-second.rpm", shell=True
    )

def common_test_python3_upgrade(install_package_fn):
    install_package_fn()
    runner = AgentRunner(PACKAGE_INSTALL)

    runner.switch_version("python3")
    runner.start()

    time.sleep(5)
    _check_version(runner, 3)

    print("Stop")
    #TODO stop does not  stop the agent. Need to find out why.
    runner.stop()
    print("stopped")

    time.sleep(1000)

    #runner = AgentRunner(PACKAGE_INSTALL)

    runner.start()

    time.sleep(5)
    _check_version(runner, 3)
