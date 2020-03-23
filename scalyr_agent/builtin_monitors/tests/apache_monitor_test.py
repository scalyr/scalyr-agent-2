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

from __future__ import unicode_literals
from __future__ import absolute_import


from scalyr_agent.builtin_monitors.apache_monitor import ApacheMonitor
from scalyr_agent.test_base import ScalyrMockHttpServerTestCase

import mock

__all__ = ["ApacheMonitorTest"]

MOCK_APACHE_STATUS_DATA = """
Total Accesses: 65
Total kBytes: 52
CPULoad: .00496689
Uptime: 604
ReqPerSec: .107616
BytesPerSec: 88.1589
BytesPerReq: 819.2
BusyWorkers: 2
IdleWorkers: 5
ConnsTotal: 1000
ConnsAsyncWriting: 10
ConnsAsyncKeepAlive: 2
ConnsAsyncClosing: 1
Scoreboard: __W___K...............................................................................................................................................
"""


def mock_apache_server_status_view_func():
    return MOCK_APACHE_STATUS_DATA


class ApacheMonitorTest(ScalyrMockHttpServerTestCase):
    @classmethod
    def setUpClass(cls):
        super(ApacheMonitorTest, cls).setUpClass()

        # Register mock route
        cls.mock_http_server_thread.app.add_url_rule(
            "/server-status", view_func=mock_apache_server_status_view_func
        )

    def test_gather_sample_200_success(self):
        url = "http://%s:%s/server-status?auto" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "apache_monitor",
            "status_url": url,
        }
        mock_logger = mock.Mock()
        monitor = ApacheMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 6)

        self.assertEqual(call_args_list[0][0], ("apache.workers.active", 2))
        self.assertEqual(call_args_list[1][0], ("apache.workers.idle", 5))
        self.assertEqual(call_args_list[2][0], ("apache.connections.active", 1000))
        self.assertEqual(call_args_list[3][0], ("apache.connections.writing", 10))
        self.assertEqual(call_args_list[4][0], ("apache.connections.idle", 2))
        self.assertEqual(call_args_list[5][0], ("apache.connections.closing", 1))

    def test_gather_sample_404_no_data_returned(self):
        url = "http://%s:%s/invalid" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "apache_monitor",
            "status_url": url,
        }
        mock_logger = mock.Mock()
        monitor = ApacheMonitor(monitor_config, mock_logger)

        monitor.gather_sample()

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.error.call_count, 2)
        self.assertTrue(
            "The URL used to request the status page appears to be incorrect"
            in mock_logger.error.call_args_list[0][0][0]
        )
        self.assertTrue("No data returned" in mock_logger.error.call_args_list[1][0][0])

    def test_gather_sample_invalid_url(self):
        url = "http://invalid"
        monitor_config = {
            "module": "apache_monitor",
            "status_url": url,
        }
        mock_logger = mock.Mock()
        monitor = ApacheMonitor(monitor_config, mock_logger)

        monitor.gather_sample()

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.error.call_count, 2)
        self.assertTrue(
            "The was an error attempting to reach the server"
            in mock_logger.error.call_args_list[0][0][0]
        )
        self.assertTrue("No data returned" in mock_logger.error.call_args_list[1][0][0])
