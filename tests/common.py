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

if False:
    from typing import Optional
    from typing import Union
    from typing import Tuple

import platform
import subprocess

import six


class PackageInstallationError(Exception):
    def __init__(self, stderr="", stdout=""):
        # type: (six.text_type, six.text_type) -> None
        super(PackageInstallationError, self).__init__()
        self.stderr = stderr
        self.stdout = stdout


def _install_rpm(file_path, upgrade=False):
    cmd = "rpm -{0} {1}".format("U" if upgrade else "i", file_path)
    exit_code, stdout, stderr = _run_command(cmd, shell=True)

    if exit_code != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr


def _install_deb(file_path):
    # NOTE: We need to specify DEBIAN_FRONTEND and PATH otherwise tests might fail depending on the
    # environment where they run
    env = {
        "DEBIAN_FRONTEND": "noninteractive",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }

    if _is_ubuntu_14_04():
        # apt on Ubuntu 14.04 doesn't support installing from a file so we use dpkg
        cmd = "dpkg -i {0}".format(file_path)
    else:
        cmd = "apt install -y -f {0}".format(file_path)

    exit_code, stdout, stderr = _run_command(cmd, shell=True, env=env)

    if exit_code != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr


def _is_ubuntu_14_04():
    # type: () -> bool
    """
    Return True if we are running on Ubuntu 14.04.
    """
    distro = platform.linux_distribution()

    return distro[0].lower() == "ubuntu" and distro[1] == "14.04"


def _run_command(cmd, shell=True, env=None):
    # type: (Union[str,list], bool, Optional[dict]) -> Tuple[int, str, str]
    env = env or {}

    if isinstance(cmd, (list, tuple)):
        command_string = " ".join(cmd)
    else:
        command_string = cmd

    print("--------------------------------------")
    print("Running command: %s" % (command_string))

    process = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    process.wait()

    exit_code = process.returncode
    stdout = process.stdout.read().decode("utf-8".strip())
    stderr = process.stderr.read().decode("utf-8").strip()

    print("Command finished")
    print("exit code: %s" % (exit_code))
    print("stdout: %s" % (stdout))
    print("stderr: %s" % (stderr))
    print("--------------------------------------")

    return exit_code, stdout, stderr


def install_rpm():
    return _install_rpm("/scalyr-agent.rpm")


def install_deb():
    return _install_deb("/scalyr-agent.deb")


def install_next_version_rpm():
    return _install_rpm("/scalyr-agent-second.rpm", upgrade=True)


def install_next_version_deb():
    return _install_deb("/scalyr-agent-second.deb")


def remove_deb():
    # NOTE: We need to specify DEBIAN_FRONTEND and PATH otherwise tests might fail depending on the
    # environment where they run
    env = {
        "DEBIAN_FRONTEND": "noninteractive",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    cmd = "apt remove -y scalyr-agent-2"
    exit_code, stdout, stderr = _run_command(cmd, shell=True, env=env)

    if exit_code != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr


def remove_rpm():
    cmd = "rpm -e scalyr-agent-2"
    exit_code, stdout, stderr = _run_command(cmd, shell=True)

    if exit_code != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr
