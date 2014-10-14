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

import os
from sys import platform as _platform

from scalyr_agent.json_lib import JsonObject
from scalyr_agent.platform_posix import PosixPlatformController
from scalyr_agent.platform_controller import DefaultPaths, TARBALL_INSTALL, DEV_INSTALL, PACKAGE_INSTALL

from __scalyr__ import get_install_root


class LinuxPlatformController(PosixPlatformController):
    """The platform controller for Linux platforms.

    This is based on the general Posix platform but also adds in Linux-specific monitors to run.
    """
    def __init__(self, install_type, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        """Initializes the POSIX platform instance.

        @param install_type: One of the constants describing the install type, such as PACKAGE_INSTALL, TARBALL_INSTALL,
            or DEV_INSTALL.

        @type install_type: int
        """
        PosixPlatformController.__init__(self, install_type, stdin=stdin, stdout=stdout, stderr=stderr)
        self.__run_system_metrics = True
        self.__run_agent_process_metrics = True

    def can_handle_current_platform(self):
        """Returns true if this platform object can handle the server this process is running on.

        @return:  True if this platform instance can handle the current server.
        @rtype: bool
        """
        return _platform.lower().startswith('linux')

    def consume_config(self, config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        This will be invoked before the scalyr-agent-2 command performs any real work and while stdout and stderr
        are still be displayed to the screen.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @type config: configuration.Configuration
        """
        PosixPlatformController.consume_config(self, config)
        self.__run_system_metrics = config.implicit_metric_monitor
        self.__run_agent_process_metrics = config.implicit_agent_process_metrics_monitor

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        if self._install_type == PACKAGE_INSTALL:
            return DefaultPaths('/var/log/scalyr-agent-2',
                                '/etc/scalyr-agent-2/agent.json',
                                '/var/lib/scalyr-agent-2')
        elif self._install_type == TARBALL_INSTALL:
            install_location = get_install_root()
            return DefaultPaths(os.path.join(install_location, 'log'),
                                os.path.join(install_location, 'config', 'agent.json'),
                                os.path.join(install_location, 'data'))
        else:
            assert(self._install_type == DEV_INSTALL)
            # For developers only.  We default to a directory ~/scalyr-agent-dev for storing
            # all log/data information, and then require a log, config, and data subdirectory in each of those.
            base_dir = os.path.join(os.path.expanduser('~'), 'scalyr-agent-dev')
            return DefaultPaths(os.path.join(base_dir, 'log'),
                                os.path.join(base_dir, 'config', 'agent.json'),
                                os.path.join(base_dir, 'data'))

    @property
    def default_monitors(self):
        """Returns the default monitors to use for this platform.

        This is guaranteed to be invoked after consume_config is called to allow implementations to make what they
        return be dependent on configuration options.

        This method should list of dicts containing monitor configuration options just as you would specify them in
        the configuration file.  The list may be empty.

        @return: The default monitors
        @rtype: list<dict>
        """
        result = []
        if self.__run_system_metrics:
            result.append(JsonObject(module='scalyr_agent.builtin_monitors.linux_system_metrics'))
        if self.__run_agent_process_metrics:
            result.append(JsonObject(module='scalyr_agent.builtin_monitors.linux_process_metrics',
                                     pid='$$', id='agent'))
        return result
