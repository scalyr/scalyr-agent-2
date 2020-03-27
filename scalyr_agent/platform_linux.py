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

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import os
from sys import platform as _platform

from scalyr_agent.json_lib import JsonObject
from scalyr_agent.platform_posix import PosixPlatformController
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.__scalyr__ import (
    get_install_root,
    TARBALL_INSTALL,
    DEV_INSTALL,
    PACKAGE_INSTALL,
)


class LinuxPlatformController(PosixPlatformController):
    """The platform controller for Linux platforms.

    This is based on the general Posix platform but also adds in Linux-specific monitors to run.
    """

    def __init__(self, stdin="/dev/null", stdout="/dev/null", stderr="/dev/null"):
        """Initializes the POSIX platform instance.
        """
        PosixPlatformController.__init__(
            self, stdin=stdin, stdout=stdout, stderr=stderr
        )

    def can_handle_current_platform(self):
        """Returns true if this platform object can handle the server this process is running on.

        @return:  True if this platform instance can handle the current server.
        @rtype: bool
        """
        return _platform.lower().startswith("linux")

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        if self._install_type == PACKAGE_INSTALL:
            return DefaultPaths(
                "/var/log/scalyr-agent-2",
                "/etc/scalyr-agent-2/agent.json",
                "/var/lib/scalyr-agent-2",
            )
        elif self._install_type == TARBALL_INSTALL:
            install_location = get_install_root()
            return DefaultPaths(
                os.path.join(install_location, "log"),
                os.path.join(install_location, "config", "agent.json"),
                os.path.join(install_location, "data"),
            )
        else:
            assert self._install_type == DEV_INSTALL
            # For developers only.  We default to a directory ~/scalyr-agent-dev for storing
            # all log/data information, and then require a log, config, and data subdirectory in each of those.
            base_dir = os.path.join(os.path.expanduser("~"), "scalyr-agent-dev")
            return DefaultPaths(
                os.path.join(base_dir, "log"),
                os.path.join(base_dir, "config", "agent.json"),
                os.path.join(base_dir, "data"),
            )

    def get_default_monitors(self, config):
        """Returns the default monitors to use for this platform.

        This method should return a list of dicts containing monitor configuration options just as you would specify
        them in the configuration file.  The list may be empty.

        @param config The configuration object to use.
        @type config configuration.Configuration

        @return: The default monitors
        @rtype: list<dict>
        """
        result = []

        if config.implicit_metric_monitor:
            result.append(
                JsonObject(module="scalyr_agent.builtin_monitors.linux_system_metrics",)
            )

        if config.implicit_agent_process_metrics_monitor:
            result.append(
                JsonObject(
                    module="scalyr_agent.builtin_monitors.linux_process_metrics",
                    pid="$$",
                    id="agent",
                )
            )
        return result
