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


from scalyr_agent.builtin_monitors.nginx_monitor import NginxMonitor
from scalyr_agent.test_base import ScalyrMockHttpServerTestCase

import mock

__all__ = ["NginxMonitorTest"]

MOCK_NGINX_STATUS_DATA = """

Active connections: 50
server accepts handled requests
 5555 6666 77777
Reading: 3 Writing: 4 Waiting: 20
""".strip()


def mock_nginx_status_view_func():
    return MOCK_NGINX_STATUS_DATA


class NginxMonitorTest(ScalyrMockHttpServerTestCase):
    @classmethod
    def setUpClass(cls):
        super(NginxMonitorTest, cls).setUpClass()

        # Register mock route
        cls.mock_http_server_thread.app.add_url_rule(
            "/nginx_status", view_func=mock_nginx_status_view_func
        )

    def test_gather_sample_200_success(self):
        url = "http://%s:%s/nginx_status" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "nginx_monitor",
            "source_address": "127.0.0.1",
            "status_url": url,
        }
        mock_logger = mock.Mock()
        monitor = NginxMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 4)

        self.assertEqual(call_args_list[0][0], ("nginx.connections.active", 50))
        self.assertEqual(call_args_list[1][0], ("nginx.connections.reading", 3))
        self.assertEqual(call_args_list[2][0], ("nginx.connections.writing", 4))
        self.assertEqual(call_args_list[3][0], ("nginx.connections.waiting", 20))

    def test_gather_sample_404_no_data_returned(self):
        url = "http://%s:%s/invalid" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "nginx_monitor",
            "source_address": "127.0.0.1",
            "status_url": url,
        }
        mock_logger = mock.Mock()
        monitor = NginxMonitor(monitor_config, mock_logger)

        monitor.gather_sample()

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.error.call_count, 2)
        self.assertTrue(
            "The URL used to request the status page appears to be incorrect"
            in mock_logger.error.call_args_list[0][0][0]
        )
        self.assertTrue("No data returned" in mock_logger.error.call_args_list[1][0][0])
