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
# author: Saurabh Jain <saurabh@scalyr.com>

__author__ = 'saurabh@scalyr.com'

import unittest
import mock
from scalyr_agent.builtin_monitors.url_monitor import UrlMonitor
from scalyr_agent.scalyr_monitor import MonitorConfig
from scalyr_agent.json_lib.objects import JsonArray, JsonObject


class UrlMonitorTestRequest(unittest.TestCase):
    """
    Tests the formation of the request for monitoring a URL
    """

    def setUp(self):
        self.legit_headers = JsonArray()
        self.legit_headers.add(JsonObject({'header': 'header_foo', 'value': 'foo'}))
        self.legit_headers.add(JsonObject({'header': 'header_bar', 'value': 'bar'}))
        self.module = 'scalyr_agent.builtin_monitors.url_monitor'

    def tearDown(self):
        pass

    def test_get_request_no_headers(self):
        mock_logger = mock.MagicMock()
        config_data = {
            'url': 'fooUrl',
            'request_method': 'GET',
            'request_data': None,
            'request_headers': [],
            'module': self.module
        }
        config = MonitorConfig(content=config_data)
        url_monitor = UrlMonitor(monitor_config=config, logger=mock_logger)

        actual_request = url_monitor.build_request()
        self.assertEqual(actual_request.get_method(), 'GET')
        self.assertFalse(actual_request.has_data())
        self.assertEqual(actual_request.header_items(), [])

    def test_get_request_with_headers(self):
        mock_logger = mock.MagicMock()
        config_data = {
            'url': 'fooUrl',
            'request_method': 'GET',
            'request_data': None,
            'request_headers': self.legit_headers,
            'module': self.module
        }
        config = MonitorConfig(content=config_data)
        url_monitor = UrlMonitor(monitor_config=config, logger=mock_logger)

        actual_request = url_monitor.build_request()
        self.assertEqual(actual_request.get_method(), 'GET')
        self.assertFalse(actual_request.has_data())
        self.assertEqual(
            actual_request.header_items(),
            [('Header_foo', 'foo'), ('Header_bar', 'bar')]
        )

    def test_post_request_with_data(self):
        mock_logger = mock.MagicMock()
        config_data = {
            'url': 'fooUrl',
            'request_method': 'POST',
            'request_data': '{fakejsonthatisnotlegit}',
            'request_headers': self.legit_headers,
            'module': self.module
        }

        config = MonitorConfig(content=config_data)
        url_monitor = UrlMonitor(monitor_config=config, logger=mock_logger)
        actual_request = url_monitor.build_request()
        self.assertEqual(actual_request.get_method(), 'POST')
        self.assertEqual(actual_request.data, '{fakejsonthatisnotlegit}')
        self.assertEqual(
            actual_request.header_items(),
            [('Header_foo', 'foo'), ('Header_bar', 'bar')]
        )

    def test_malformed_headers(self):
        mock_logger = mock.MagicMock()
        config_data = {
            'url': 'fooUrl',
            'request_method': 'POST',
            'request_data': '{fakejsonthatisnotlegit}',
            'request_headers': 'not legit headers',
            'module': self.module
        }

        config = MonitorConfig(content=config_data)
        with self.assertRaises(Exception):
            _ = UrlMonitor(monitor_config=config, logger=mock_logger)
