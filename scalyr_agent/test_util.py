# Copyright 2019 Scalyr Inc.
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
#
# author: Edward Chee <echee@scalyr.com>

__author__ = 'echee@scalyr.com'


import atexit
import logging
import os
import shutil
import tempfile

import scalyr_agent.util as scalyr_util

from scalyr_agent import json_lib
from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.json_lib import JsonArray, JsonObject
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_logging import AgentLogger


class ScalyrTestUtils(object):

    @staticmethod
    def create_configuration(extra_toplevel_config=None):
        """Creates a blank configuration file with default values. Optionally overwrites top-level key/values.
        Sets api_key to 'fake' unless defined in extra_toplevel_config

        @param extra_toplevel_config: Dict of top-level key/value objects to overwrite.
        @return: The configuration object
        @rtype: Configuration
        """
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        toplevel_config = {'api_key': 'fake'}
        if extra_toplevel_config:
            toplevel_config.update(extra_toplevel_config)

        fp = open(config_file, 'w')
        fp.write(json_lib.serialize(JsonObject(**toplevel_config)))
        fp.close()

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        config = Configuration(config_file, default_paths, None)
        config.parse()

        # we need to delete the config dir when done
        atexit.register(shutil.rmtree, config_dir)

        return config

    @staticmethod
    def create_test_monitors_manager(config_monitors=None, platform_monitors=None, extra_toplevel_config=None,
                                     null_logger=False, fake_clock=False, set_daemon=False):
        """Create a test MonitorsManager

        @param config_monitors: config monitors
        @param platform_monitors: platform monitors
        @param extra_toplevel_config: dict of extra top-level key value objects
        @param null_logger: If True, set all monitors to log to Nullhandler
        @param fake_clock: If non-null, the manager and all it's monitors' _run_state's will use the provided fake_clock
        """
        monitors_json_array = JsonArray()
        if config_monitors:
            for entry in config_monitors:
                monitors_json_array.add(JsonObject(content=entry))

        extras = {'monitors': monitors_json_array}
        if extra_toplevel_config:
            extras.update(extra_toplevel_config)

        config = ScalyrTestUtils.create_configuration(extra_toplevel_config=extras)
        config.parse()

        if not platform_monitors:
            platform_monitors = []
        # noinspection PyTypeChecker
        test_manager = MonitorsManager(config, FakePlatform(platform_monitors))

        if null_logger:
            # Override Agent Logger to prevent writing to disk
            for monitor in test_manager.monitors:
                monitor._logger = FakeAgentLogger('fake_agent_logger')

        if fake_clock:
            for monitor in test_manager.monitors + [test_manager]:
                monitor._run_state = scalyr_util.RunState(fake_clock=fake_clock)

        return test_manager


class FakeAgentLogger(AgentLogger):
    def __init__(self, name):
        super(FakeAgentLogger, self).__init__(name)
        if not len(self.handlers):
            self.addHandler(logging.NullHandler())


class FakePlatform(object):
    """Fake implementation of PlatformController.

    Only implements the one method required for testing MonitorsManager.
    """
    def __init__(self, default_monitors):
        self.__monitors = default_monitors

    def get_default_monitors(self, _):
        return self.__monitors
