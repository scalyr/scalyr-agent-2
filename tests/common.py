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

import subprocess

import six


class PackageInstallationError(Exception):
    def __init__(self, stderr="", stdout=""):
        # type: (six.text_type, six.text_type) -> None
        super(PackageInstallationError, self).__init__()
        self.stderr = stderr
        self.stdout = stdout


def _install_rpm(file_path, upgrade=False):
    process = subprocess.Popen(
        "rpm -{0} {1}".format("U" if upgrade else "i", file_path),
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    process.wait()

    stdout = process.stdout.read().decode("utf-8")
    stderr = process.stderr.read().decode("utf-8")

    if process.returncode != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr


def _install_deb(file_path):
    # NOTE: We need to specify DEBIAN_FRONTEND and PATH otherwise tests might fail depending on the
    # environment where they run
    env = {
        "DEBIAN_FRONTEND": "noninteractive",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    process = subprocess.Popen(
        "apt install -y -f {0}".format(file_path),
        shell=True,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    process.wait()

    stdout = process.stdout.read().decode("utf-8")
    stderr = process.stderr.read().decode("utf-8")

    if process.returncode != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr


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
    process = subprocess.Popen(
        "apt remove -y scalyr-agent-2",
        shell=True,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    process.wait()


def remove_rpm():
    process = subprocess.Popen(
        "rpm -e scalyr-agent-2",
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    process.wait()

    stdout = process.stdout.read()
    stderr = process.stderr.read()

    if process.returncode != 0:
        raise PackageInstallationError(stderr=stderr, stdout=stdout)

    return stdout, stderr
