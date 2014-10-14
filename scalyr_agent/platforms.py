# Copyright 2014 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

from scalyr_agent.platform_linux import LinuxPlatformController
from scalyr_agent.platform_posix import PosixPlatformController
from scalyr_agent.platform_controller import PlatformController


def register_supported_platforms():
    """Register the PlatformControllers for all platforms supported by this server.
    """
    PlatformController.register_platform(LinuxPlatformController)
    # TODO: Do not register the POSIX platform for Windows when Windows is supported.
    PlatformController.register_platform(PosixPlatformController)