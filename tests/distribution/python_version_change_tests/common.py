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
from __future__ import unicode_literals

import os
import time
import json
import shutil
import stat
from io import open

import six
import pytest

from scalyr_agent import compat

from tests.utils.compat import Path
from tests.utils.common import get_shebang_from_file
from tests.utils.agent_runner import AgentRunner, PACKAGE_INSTALL
from tests.common import PackageInstallationError

SCALYR_PACKAGE_BIN_PATH = Path("/", "usr", "share", "scalyr-agent-2", "bin")
BINARY_DIR_PATH = Path("/", "usr", "bin")


def _get_python_major_version(runner):
    status = json.loads(runner.status_json())

    version_string = status["python_version"]

    version = int(version_string[0])

    return version


def _remove_python(command):
    try:
        os.remove(six.text_type(BINARY_DIR_PATH / command))
    except IOError:
        pass


def _get_current_config_script_name():
    return Path(
        os.readlink(six.text_type(SCALYR_PACKAGE_BIN_PATH / "scalyr-agent-2-config"))
    ).name


def _link_to_default_python(command):
    """
    Specify on which python version 'python' command will be mapped.
    :param command: python2|python3
    :return:
    """
    python_path = six.text_type(BINARY_DIR_PATH / "python")
    try:
        os.remove(python_path)
    except:
        pass

    real_executable_path = os.readlink(six.text_type(BINARY_DIR_PATH / command))
    os.symlink(six.text_type(BINARY_DIR_PATH / real_executable_path), python_path)


def _mock_python_binary_version(python_binary_name, version):
    # type: (six.text_type, six.text_type) -> None
    """
    Replace python binary with dummy srtipt that only print fake python version string.
    :return:
    """
    binary_path = BINARY_DIR_PATH / python_binary_name
    binary_path_backup_path = Path(six.text_type(binary_path) + "_bc")

    # this function was used previously delete old backup.
    if binary_path_backup_path.exists():
        shutil.copy(
            six.text_type(binary_path_backup_path), six.text_type(binary_path),
        )
        os.remove(six.text_type(binary_path_backup_path))

    if not version:
        return

    if not binary_path.exists():
        return

    # make backup of the original binary in case if we want to keep useing it.
    shutil.copy(six.text_type(binary_path), six.text_type(binary_path_backup_path))
    os.remove(six.text_type(binary_path))

    # write new source to binary file. Now it just returns fake version.
    with binary_path.open("w") as f:
        f.write("#!/bin/bash\n")
        f.write("echo Python {0}\n".format(version))

    os.chmod(six.text_type(binary_path), stat.S_IWRITE | stat.S_IEXEC)


def _mock_binaries(python, python2, python3):
    _mock_python_binary_version("python", python)
    _mock_python_binary_version("python2", python2)
    _mock_python_binary_version("python3", python3)


def common_version_test(
    runner,
    install_package_fn,
    remove_package_fn,
    expected_conf_file_name,
    *python_versions,
    **kwargs
):
    """
    Replace real python binaries with dummy scripts which only can print fake versions.

    :param runner: The agent runner
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    :param remove_package_fn: callable that removes package.
    :param expected_conf_file_name: name of the "conf_main*" file, helps to be sure that python version is switched.
    :param python_versions: mock real python binaries with with dummy bash scripts, which only prints version.
    By those mocks we make installer skip those binaries as invalid for the agent.
    :param kwargs:
    :return:
    """
    install_fails = kwargs.get("install_fails", False)

    _mock_binaries(*python_versions)

    if install_fails:
        with pytest.raises(PackageInstallationError):
            install_package_fn()
        return
    else:
        stdout, _ = install_package_fn()

    assert _get_current_config_script_name() == expected_conf_file_name

    _mock_binaries("", "", "")

    runner.switch_version("default")

    remove_package_fn()


def common_test_no_python(install_package_fn):
    """
    Test package installation on the machine without any python installed,so it must fail.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # remove all python binaries.
    _remove_python("python")
    _remove_python("python2")
    _remove_python("python3")

    with pytest.raises(PackageInstallationError) as err_info:
        install_package_fn()

    excepton = err_info.value

    # make sure that python is not found by searching needed output.
    assert "Python interpreter is not found." in excepton.stdout


def common_test_only_python_mapped_to_python2(
    install_package_fn, install_next_version_fn
):
    """
    Test package installation on the machine with python2 but there is only 'python' command which is mapped on to it.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # map 'python' command on to python2
    _link_to_default_python("python2")
    _remove_python("python2")
    _remove_python("python3")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python' mapped on to python2
    assert "The Scalyr agent will use the default python." in stdout

    # 'scalyr-agent-2-config' command must be a symlink to config_main.py
    assert _get_current_config_script_name() == "config_main.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 2
    runner.stop()

    # install next version of the package
    install_next_version_fn()

    # the source file should be "config_main.py"
    assert _get_current_config_script_name() == "config_main.py"


def common_test_only_python_mapped_to_python3(
    install_package_fn, install_next_version_fn
):
    """
    Test package installation on the machine with python3 but there is only 'python' command which is mapped on to it.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # map 'python' command on to python3
    _link_to_default_python("python3")
    _remove_python("python2")
    _remove_python("python3")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python' mapped on to python3
    assert "The Scalyr agent will use the default python." in stdout

    # 'scalyr-agent-2-config' command must be a symlink to config_main.py
    assert _get_current_config_script_name() == "config_main.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 3
    runner.stop()

    # install next version of the package
    install_next_version_fn()

    # the source file should be "config_main.py"
    assert _get_current_config_script_name() == "config_main.py"


def common_test_python2(install_package_fn, install_next_version_fn):
    """
    Test package installation on machine with python2
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # remove python and python3 to make installer see only python2
    _remove_python("python")
    _remove_python("python3")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python2'.
    assert "The defaut 'python' command is not found, will use python2 binary for running the agent."

    # 'scalyr-agent-2-config' command must be a symlink to config_main_py2.py
    assert _get_current_config_script_name() == "config_main_py2.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()

    time.sleep(1)

    assert _get_python_major_version(runner) == 2
    runner.stop()

    # install next version of the package
    stdout, _ = install_next_version_fn()
    # the source file should be "config_main_py2.py"
    assert _get_current_config_script_name() == "config_main_py2.py"


def common_test_python3(install_package_fn, install_next_version_fn):
    """
    Test package installation on machine with python3
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # remove python and python2 to make installer see only python3
    _remove_python("python")
    _remove_python("python2")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python3'.
    assert "The defaut 'python' command is not found, will use python2 binary for running the agent."
    assert "The 'python2' command is not found, will use python3 binary for running the agent."

    # 'scalyr-agent-2-config' command must be a symlink to config_main_py3.py
    assert _get_current_config_script_name() == "config_main_py3.py"

    runner = AgentRunner(PACKAGE_INSTALL)

    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 3
    runner.stop()

    # install next version of the package
    stdout, _ = install_next_version_fn()
    # the source file should be "config_main_py3.py"
    assert _get_current_config_script_name() == "config_main_py3.py"


def common_test_switch_default_to_python2(install_package_fn, install_next_version_fn):
    """
    Test package installation on machine with python and python2.
    Package installer should pick 'python' by default and then we switch it to python2 and get back to default.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    # let python2 be default.
    _link_to_default_python("python2")
    _remove_python("python3")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python' mapped on to python2.
    assert "The Scalyr agent will use the default python." in stdout

    assert _get_current_config_script_name() == "config_main.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 2

    # switching to python2
    runner.stop()
    runner.switch_version("python2")
    assert _get_current_config_script_name() == "config_main_py2.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 2
    runner.stop()

    # install next version of the package and check that links are the same.
    stdout, _ = install_next_version_fn()
    # Installer must not switch to default python.
    assert "Use python2 version from previous installation." in stdout
    # the source file should be "config_main_py3.py"
    assert _get_current_config_script_name() == "config_main_py2.py"

    # switching back to default python
    runner.switch_version("default")
    assert _get_current_config_script_name() == "config_main.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 2


def common_test_switch_default_to_python3(install_package_fn, install_next_version_fn):
    """
    Test package installation on machine with python and python3.
    Package installer should pick 'python' by default and then we switch it to python3.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """
    # let python2 be default.
    _link_to_default_python("python2")
    _remove_python("python2")

    stdout, _ = install_package_fn()

    # make sure that installer has found 'python' mapped on to python3.
    assert "The Scalyr agent will use the default python." in stdout

    assert _get_current_config_script_name() == "config_main.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 2

    # switching to python3
    runner.stop()
    runner.switch_version("python3")
    assert _get_current_config_script_name() == "config_main_py3.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 3
    runner.stop()

    # install next version of the package and check that links are the same.
    stdout, _ = install_next_version_fn()
    # Installer must not switch to default python.
    assert "Use python3 version from previous installation." in stdout
    # the source file should be "config_main_py3.py"
    assert _get_current_config_script_name() == "config_main_py3.py"

    # switching back to default python
    runner.switch_version("default")
    assert _get_current_config_script_name() == "config_main.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 2


def common_test_switch_command_works_without_agent_config(install_package_fn):
    """
    Verify that the Python version switch command works if the config file is not present or
    doesn't contain a valid API key.

    This is important because this command may run as part of package postinstall script when the
    key won't be configured yet.

    Basically it asserts that the switch command doesn't rely agent config being present and
    correctly configured.
    """
    install_package_fn()

    runner = AgentRunner(PACKAGE_INSTALL)

    # Make sure the config is not present
    agent_config_path = "/etc/scalyr-agent-2/agent.json"
    agent_config_d_path = "/etc/scalyr-agent-2/agent.d"

    if os.path.isfile(agent_config_path):
        os.unlink(agent_config_path)

    if os.path.isdir(agent_config_d_path):
        shutil.rmtree(agent_config_d_path)

    # Make sure no SCALYR_ environment variables are set
    env = compat.os_environ_unicode.copy()

    for key in list(env.keys()):
        if key.lower().startswith("scalyr"):
            del env[key]

    binary_path = os.path.join("/", "usr", "share", "scalyr-agent-2", "bin")

    scalyr_agent_2_target = os.path.join(binary_path, "scalyr-agent-2")
    scalyr_agent_2_config_target = os.path.join(binary_path, "scalyr-agent-2-config")

    # Default should be python2
    shebang_line_main = get_shebang_from_file(scalyr_agent_2_target)
    shebang_line_config = get_shebang_from_file(scalyr_agent_2_config_target)
    assert shebang_line_main == "#!/usr/bin/env python2"
    assert shebang_line_config == "#!/usr/bin/env python2"

    # Switch to python3
    runner.switch_version("python3", env=env)

    shebang_line_main = get_shebang_from_file(scalyr_agent_2_target)
    shebang_line_config = get_shebang_from_file(scalyr_agent_2_config_target)
    assert shebang_line_main == "#!/usr/bin/env python3"
    assert shebang_line_config == "#!/usr/bin/env python3"

    # Switch back to python2
    runner.switch_version("python2", env=env)

    shebang_line_main = get_shebang_from_file(scalyr_agent_2_target)
    shebang_line_config = get_shebang_from_file(scalyr_agent_2_config_target)
    assert shebang_line_main == "#!/usr/bin/env python2"
    assert shebang_line_config == "#!/usr/bin/env python2"

    # Write a config with invalid config, this way we ensure config is indeed not parsed by that
    # command even if it's present
    mock_config = {
        "api_key": "",
        "scalyr_server": "agent.scalyr.com",
    }

    with open(agent_config_path, "w") as fp:
        fp.write(json.dumps(mock_config))

    # Switch to python3
    runner.switch_version("python3", env=env)

    shebang_line_main = get_shebang_from_file(scalyr_agent_2_target)
    shebang_line_config = get_shebang_from_file(scalyr_agent_2_config_target)
    assert shebang_line_main == "#!/usr/bin/env python3"
    assert shebang_line_config == "#!/usr/bin/env python3"


def common_test_switch_python2_to_python3(install_package_fn, install_next_version_fn):
    """
    Test package installation on machine with both python2 and python3 but without default 'python'.
    Package installer should pick python2 by default and then we switch to the python3.
    :param install_package_fn: callable that installs package with appropriate type to the current machine OS.
    """

    _remove_python("python")

    install_package_fn()
    assert _get_current_config_script_name() == "config_main_py2.py"

    runner = AgentRunner(PACKAGE_INSTALL)
    runner.start()
    time.sleep(1)

    assert _get_python_major_version(runner) == 2

    # switching to python3
    runner.stop()
    runner.switch_version("python3")
    assert _get_current_config_script_name() == "config_main_py3.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 3
    runner.stop()

    # install next version of the package and check that links are the same.
    stdout, _ = install_next_version_fn()
    # Installer must not switch to default python.
    assert "Use python3 version from previous installation." in stdout
    # the source file should be "config_main_py3.py"
    assert _get_current_config_script_name() == "config_main_py3.py"

    # switching bach to python2
    runner.switch_version("python2")
    assert _get_current_config_script_name() == "config_main_py2.py"
    runner.start()
    time.sleep(1)
    assert _get_python_major_version(runner) == 2
