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

from __future__ import print_function
from __future__ import absolute_import

import os
import time
import json

from tests.utils.compat import Path
from tests.utils.agent_runner import AgentRunner, PACKAGE_INSTALL


def _get_python_major_version(runner):
    status = json.loads(runner.status_json())

    version_string = status["python_version"]

    version = int(version_string[0])

    return version


def common_test_python3(install_package_fn):
    """
    Test package installation on machine with python3
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # remove pythn and python2 to make installer see only python3
    try:
        # some distros do not have 'python' command.
        os.remove(str(Path("/", "usr", "bin", "python")))
    except IOError:
        pass
    os.remove(str(Path("/", "usr", "bin", "python2")))

    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 3


def common_test_python2(install_package_fn):
    """
    Test package installation on machine with python2
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """
    print("")
    # remove python3 to make installer see only python2
    os.remove(str(Path("/", "usr", "bin", "python3")))

    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()

    time.sleep(1)

    assert _get_python_major_version(runner) == 2


def common_test_python2to3(install_package_fn):
    """
    Test package installation on machine with both python2 and python3.
    PAckage installer should pick python2 by default.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    install_package_fn()
    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 2

    # switching to python3
    runner.stop()
    runner.switch_version("python3")
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 3


def common_test_python3_upgrade(install_package_fn, install_next_version_fn):
    """
    Test package upgrade on the machine where python3 was chosen.
    Need to be sure that python3 remains as chosen version after upgrade.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    :param install_next_version_fn: callable that installs next version of the package.
    """
    install_package_fn()
    runner = AgentRunner(PACKAGE_INSTALL)
    runner.switch_version("python3")
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 3
    runner.stop()
    install_next_version_fn()
    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 3
