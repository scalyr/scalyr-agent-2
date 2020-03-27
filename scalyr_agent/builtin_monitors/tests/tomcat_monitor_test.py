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


from scalyr_agent.builtin_monitors.tomcat_monitor import TomcatMonitor
from scalyr_agent.test_base import ScalyrMockHttpServerTestCase

import mock

__all__ = ["TomcatMonitorTest"]

MOCK_TOMCAT_STATUS_dATA = """
<h1>JVM</h1><p> Free memory: 355.58 MB Total memory: 833.13 MB Max memory: 2900.00 MB</p><table border="0"><thead><tr><th>Memory Pool</th><th>Type</th><th>Initial</th><th>Total</th><th>Maximum</th><th>Used</th></tr></thead><tbody><tr><td>Eden Space</td><td>Heap memory</td><td>34.12 MB</td><td>229.93 MB</td><td>800.00 MB</td><td>12.47 MB (1%)</td></tr><tr><td>Survivor Space</td><td>Heap memory</td><td>4.25 MB</td><td>28.68 MB</td><td>100.00 MB</td><td>2.22 MB (2%)</td></tr><tr><td>Tenured Gen</td><td>Heap memory</td><td>85.37 MB</td><td>574.51 MB</td><td>2000.00 MB</td><td>462.84 MB (23%)</td></tr><tr><td>Code Cache</td><td>Non-heap memory</td><td>2.43 MB</td><td>7.00 MB</td><td>48.00 MB</td><td>6.89 MB (14%)</td></tr><tr><td>Perm Gen</td><td>Non-heap memory</td><td>128.00 MB</td><td>128.00 MB</td><td>512.00 MB</td><td>52.57 MB (10%)</td></tr></tbody></table><h1>"http-nio-8080"</h1><p> Max threads: 200 Current thread count: 10 Current thread busy: 3 Keeped alive sockets count: 1<br> Max processing time: 301 ms Processing time: 71.068 s Request count: 10021 Error count: 2996 Bytes received: 0.00 MB Bytes sent: 3.18 MB</p><table border="0"><tr><th>Stage</th><th>Time</th><th>B Sent</th><th>B Recv</th><th>Client (Forwarded)</th><th>Client (Actual)</th><th>VHost</th><th>Request</th></tr><tr><td><strong>F</strong></td><td>1486364749526 ms</td><td>0 KB</td><td>0 KB</td><td>185.40.4.169</td><td>185.40.4.169</td><td nowrap>?</td><td nowrap class="row-left">? ? ?</td></tr><tr><td><strong>F</strong></td><td>1486364749526 ms</td><td>0 KB</td><td>0 KB</td><td>185.40.4.169</td><td>185.40.4.169</td><td nowrap>?</td><td nowrap class="row-left">? ? ?</td></tr><tr><td><strong>R</strong></td><td>?</td><td>?</td><td>?</td><td>?</td><td>?</td><td>?</td></tr><tr><td><strong>S</strong></td><td>36 ms</td><td>0 KB</td><td>0 KB</td><td>106.51.39.130</td><td>106.51.39.130</td><td nowrap>104.197.119.177</td><td nowrap class="row-left">GET /manager/status?org.apache.catalina.filters.CSRF_NONCE=072F9F6884D94C5D7B30D1D34CE61BD9 HTTP/1.1</td></tr><tr><td><strong>R</strong></td><td>?</td><td>?</td><td>?</td><td>?</td><td>?</td><td>?</td></tr></table><p>P: Parse and prepare request S: Service F: Finishing R: Ready K: Keepalive</p><hr size="1" noshade="noshade">
"""


def mock_tomcat_status_view_func():
    return MOCK_TOMCAT_STATUS_dATA


class TomcatMonitorTest(ScalyrMockHttpServerTestCase):
    @classmethod
    def setUpClass(cls):
        super(TomcatMonitorTest, cls).setUpClass()

        # Register mock route
        cls.mock_http_server_thread.app.add_url_rule(
            "/manager/status", view_func=mock_tomcat_status_view_func
        )

    def test_gather_sample_200_success(self):
        url = "http://%s:%s/manager/status" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "tomcat_monitor",
            "monitor_url": url,
        }
        mock_logger = mock.Mock()
        monitor = TomcatMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 12)

        self.assertEqual(
            call_args_list[0][0],
            ("tomcat.runtime.network_bytes", 0.0, {"type": "received"}),
        )
        self.assertEqual(
            call_args_list[1][0],
            ("tomcat.runtime.network_bytes", 3.18, {"type": "sent"}),
        )
        self.assertEqual(
            call_args_list[2][0], ("tomcat.runtime.error_count", 2996, None)
        )
        self.assertEqual(
            call_args_list[3][0],
            ("tomcat.runtime.memory_bytes", 355.58, {"type": "free"}),
        )
        self.assertEqual(
            call_args_list[4][0],
            ("tomcat.runtime.memory_bytes", 2900.0, {"type": "max"}),
        )
        self.assertEqual(
            call_args_list[5][0],
            ("tomcat.runtime.memory_bytes", 833.13, {"type": "total"}),
        )
        self.assertEqual(
            call_args_list[6][0], ("tomcat.runtime.processing_time", 71068.0, None)
        )
        self.assertEqual(
            call_args_list[7][0], ("tomcat.runtime.processing_time_max", 301.0, None)
        )
        self.assertEqual(
            call_args_list[8][0], ("tomcat.runtime.request_count", 10021, None)
        )
        self.assertEqual(
            call_args_list[9][0], ("tomcat.runtime.threads", 3, {"type": "busy"})
        )
        self.assertEqual(
            call_args_list[10][0], ("tomcat.runtime.threads", 10, {"type": "active"})
        )
        self.assertEqual(
            call_args_list[11][0], ("tomcat.runtime.threads", 200, {"type": "max"})
        )

    def test_gather_sample_404_no_data_returned(self):
        url = "http://%s:%s/invalid" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )
        monitor_config = {
            "module": "tomcat_monitor",
            "monitor_url": url,
        }
        mock_logger = mock.Mock()
        monitor = TomcatMonitor(monitor_config, mock_logger)

        monitor.gather_sample()

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.error.call_count, 1)
        self.assertTrue(
            "The URL used to request the status page appears to be incorrect"
            in mock_logger.error.call_args_list[0][0][0]
        )

    def test_gather_sample_invalid_url(self):
        url = "http://invalid"
        monitor_config = {
            "module": "tomcat_monitor",
            "monitor_url": url,
        }
        mock_logger = mock.Mock()
        monitor = TomcatMonitor(monitor_config, mock_logger)

        monitor.gather_sample()

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.error.call_count, 1)
        self.assertTrue(
            "The was an error attempting to reach the server"
            in mock_logger.error.call_args_list[0][0][0]
        )
