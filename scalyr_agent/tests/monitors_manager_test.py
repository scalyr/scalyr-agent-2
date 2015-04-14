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
import tempfile

from scalyr_agent.configuration import Configuration
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent import json_lib

from scalyr_agent.test_base import ScalyrTestCase


class MonitorsManagerTest(ScalyrTestCase):
    def test_single_module(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            }
        ], [])
        self.assertEquals(len(test_manager.monitors), 1)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor()')

    def test_multiple_modules(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
        ], [])

        self.assertEquals(len(test_manager.monitors), 2)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor(1)')
        self.assertEquals(test_manager.monitors[1].monitor_name, 'test_monitor(2)')

    def test_module_with_id(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'id': 'first',
                'gauss_mean': 0
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
        ], [])
        self.assertEquals(len(test_manager.monitors), 2)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor(first)')
        self.assertEquals(test_manager.monitors[1].monitor_name, 'test_monitor(2)')

    def __create_test_instance(self, config_monitors, platform_monitors):
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        monitors_json_array = JsonArray()

        for entry in config_monitors:
            monitors_json_array.add(JsonObject(content=entry))

        fp = open(config_file, 'w')
        fp.write(json_lib.serialize(JsonObject(api_key='fake', monitors=monitors_json_array)))
        fp.close()

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        config = Configuration(config_file, default_paths)
        config.parse()
        # noinspection PyTypeChecker
        return MonitorsManager(config, FakePlatform(platform_monitors))


class FakePlatform(object):
    """Fake implementation of PlatformController.

    Only implements the one methd required for testing MonitorsManager.
    """
    def __init__(self, default_monitors):
        self.__monitors = default_monitors

    def get_default_monitors(self, _):
        return self.__monitors
