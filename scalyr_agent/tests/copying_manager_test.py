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
from scalyr_agent.copying_manager import CopyingParameters, CopyingManager
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent import json_lib

ONE_MB = 1024 * 1024


class CopyingParamsTest(ScalyrTestCase):
    def setUp(self):
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, 'agentConfig.json')
        self.__config_fragments_dir = os.path.join(self.__config_dir, 'configs.d')
        os.makedirs(self.__config_fragments_dir)

        fp = open(self.__config_file, 'w')
        fp.write('{api_key: "fake"}')
        fp.close()

        config = self.__create_test_configuration_instance()
        config.parse()
        self.test_params = CopyingParameters(config)

    def test_initial_settings(self):
        self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MB)
        self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_no_events_being_sent(self):
        for i in range(0, 5):
            self.test_params.update_params('success', 0)
            self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MB)
            self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_small_events_being_sent(self):
        self.test_params.current_sleep_interval = 1
        self.run_test_case('success', 10 * 1024, [1.5, ONE_MB], [2.25, ONE_MB], [3.375, ONE_MB], [5, ONE_MB])

    def test_too_many_events_being_sent(self):
        self.test_params.current_sleep_interval = 5

        self.run_test_case('success', 200 * 1024, [3.0, ONE_MB], [1.8, ONE_MB], [1.08, ONE_MB], [1, ONE_MB])

    def test_request_too_big(self):
        self.test_params.current_sleep_interval = 1

        self.test_params.update_params('requestTooLarge', 300 * 1024)
        self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, 150 * 1024)

        self.test_params.update_params('requestTooLarge', 150 * 1024)
        self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, 100 * 1024)

    def test_error_back_off(self):
        self.test_params.current_sleep_interval = 3
        self.run_test_case('error', 200 * 1024, [4.5, ONE_MB], [6.75, ONE_MB], [10.125, ONE_MB], [15.1875, ONE_MB],
                           [22.78125, ONE_MB], [30, ONE_MB])

    def run_test_case(self, status, bytes_sent, *expected_sleep_interval_allowed_bytes):
        """Verifies that when test_params is updated with the specified status and bytes sent the current sleep
        interval and allowed bytes is updated to the given values.

        This will call test_params.update_params N times where N is the number of additional arguments supplied.
        After the ith invocation of test_params.update_params, the values for the current_sleep_interval and
        current_bytes_allowed_to_send will be checked against the ith additional parameter.

        @param status: The status to use when invoking test_params.update_params.
        @param bytes_sent: The number of bytes sent to use when invoking test_params.update_params.
        @param expected_sleep_interval_allowed_bytes: A variable number of two element arrays where the first element
            is the expected value for current_sleep_interval and the second is the expected value of
            current_bytes_allowed_to_send. Each subsequent array represents what those values should be after invoking
            test_params.update_param again.
        """
        for expected_result in expected_sleep_interval_allowed_bytes:
            self.test_params.update_params(status, bytes_sent)
            self.assertAlmostEquals(self.test_params.current_sleep_interval, expected_result[0])
            self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, expected_result[1])

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config['path']

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config['module']
            self.config = config
            self.log_config = {'path': self.module_name.split('.')[-1] + '.log'}

    def __create_test_configuration_instance(self):

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')
        return Configuration(self.__config_file, default_paths)


class CopyingManagerInitializationTest(ScalyrTestCase):

    def test_from_config_file(self):
        test_manager = self.__create_test_instance([
            {
                'path': '/tmp/hi.log'
            }
        ], [])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/tmp/hi.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/var/log/scalyr-agent-2/agent.log')

    def test_from_monitors(self):
        test_manager = self.__create_test_instance([
        ], [
            {
                'path': '/tmp/hi_monitor.log',
            }
        ])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/tmp/hi_monitor.log')
        self.assertEquals(test_manager.log_matchers[1].config['attributes']['parser'], 'agent-metrics')

    def test_multiple_monitors_for_same_file(self):
        test_manager = self.__create_test_instance([
        ], [
            {'path': '/tmp/hi_monitor.log'},
            {'path': '/tmp/hi_monitor.log'},
            {'path': '/tmp/hi_second_monitor.log'}
        ])
        self.assertEquals(len(test_manager.log_matchers), 3)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/tmp/hi_monitor.log')
        self.assertEquals(test_manager.log_matchers[1].config['attributes']['parser'], 'agent-metrics')
        self.assertEquals(test_manager.log_matchers[2].config['path'], '/tmp/hi_second_monitor.log')
        self.assertEquals(test_manager.log_matchers[2].config['attributes']['parser'], 'agent-metrics')

    def test_monitor_log_config_updated(self):
        test_manager = self.__create_test_instance([
        ], [
            {'path': 'hi_monitor.log'},
        ])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/var/log/scalyr-agent-2/hi_monitor.log')

        # We also verify the monitor instance itself's log config object was updated to have the full path.
        self.assertEquals(self.__monitor_fake_instances[0].log_config['path'], '/var/log/scalyr-agent-2/hi_monitor.log')

    def __create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        logs_json_array = JsonArray()

        for entry in configuration_logs_entry:
            logs_json_array.add(JsonObject(content=entry))

        fp = open(config_file, 'w')
        fp.write(json_lib.serialize(JsonObject(api_key='fake', logs=logs_json_array)))
        fp.close()

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        config = Configuration(config_file, default_paths)
        config.parse()

        self.__monitor_fake_instances = []
        for monitor_log_config in monitors_log_configs:
            self.__monitor_fake_instances.append(FakeMonitor(monitor_log_config))

        # noinspection PyTypeChecker
        return CopyingManager(config, self.__monitor_fake_instances)


class FakeMonitor(object):
    def __init__(self, monitor_log_config):
        self.module_name = 'fake_monitor'
        self.log_config = monitor_log_config
