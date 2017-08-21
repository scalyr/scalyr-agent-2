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
from scalyr_agent.json_lib.objects import JsonArray, JsonObject


class UrlMonitorTestRequest(unittest.TestCase):
    """
    Tests the formation of the request for monitoring a URL
    """

    def setUp(self):
        self.legit_headers = JsonArray()
        self.legit_headers.add(JsonObject({'header': 'header_foo', 'value': 'foo'}))
        self.legit_headers.add(JsonObject({'header': 'header_bar', 'value': 'bar'}))

    def tearDown(self):
        pass

    def testGetRequestNoHeaders(self):
        mock_logger = mock.MagicMock()
        actual_request = UrlMonitor.form_request('fooUrl', 'GET', None, [], mock_logger)
        self.assertEqual(actual_request.get_method(), 'GET')
        self.assertFalse(actual_request.has_data())
        self.assertEqual(actual_request.header_items(), [])

    def testGetRequestWithHeaders(self):
        mock_logger = mock.MagicMock()
        actual_request = UrlMonitor.form_request(
            'fooUrl',
            'GET',
            None,
            self.legit_headers,
            mock_logger
        )
        self.assertEqual(actual_request.get_method(), 'GET')
        self.assertFalse(actual_request.has_data())
        self.assertEqual(
            actual_request.header_items(),
            [('Header_foo', 'foo'), ('Header_bar', 'bar')]
        )

    def testPostRequestWithData(self):
        mock_logger = mock.MagicMock()
        actual_request = UrlMonitor.form_request(
            'fooUrl',
            'POST',
            '{fakejsonthatisnotlegit}',
            self.legit_headers,
            mock_logger
        )
        self.assertEqual(actual_request.get_method(), 'POST')
        self.assertEqual(actual_request.data, '{fakejsonthatisnotlegit}')
        self.assertEqual(
            actual_request.header_items(),
            [('Header_foo', 'foo'), ('Header_bar', 'bar')]
        )

    def testMalformedheaders(self):
        mock_logger = mock.MagicMock()
        UrlMonitor.form_request(
            'fooUrl',
            'POST',
            '{fakejsonthatisnotlegit}',
            'not legit header',
            mock_logger
        )
        mock_logger.emit_value.assert_called()
