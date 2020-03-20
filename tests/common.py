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


def _install_rpm(file_path, upgrade=False):
    subprocess.check_call(
        "rpm -{0} {1}".format("U" if upgrade else "i", file_path),
        shell=True,
        stdin=subprocess.PIPE,
    )


def _install_deb(file_path):
    subprocess.check_call(
        "apt install -y -f {0}".format(file_path), shell=True, stdin=subprocess.PIPE
    )


def install_rpm():
    _install_rpm("/scalyr-agent.rpm")


def install_deb():
    _install_deb("/scalyr-agent.deb")


def install_next_version_rpm():
    _install_rpm("/scalyr-agent-second.rpm", upgrade=True)


def install_next_version_deb():
    _install_deb("/scalyr-agent-second.deb")
