# Copyright 2014-2022 Scalyr Inc.
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

import time
import socket
import pickle
import random

from scalyr_agent import compat
from scalyr_agent.builtin_monitors.graphite_monitor import GraphiteMonitor
from scalyr_agent.builtin_monitors.graphite_monitor import GraphiteTextServer
from scalyr_agent.builtin_monitors.graphite_monitor import GraphitePickleServer
from scalyr_agent.test_base import ScalyrTestCase

import mock

__all__ = [
    "GraphiteMonitorTestCase",
    "GraphiteMonitorTextServerTestCase",
    "GraphiteMonitorPickleServerTestCase",
]


class GraphiteMonitorTestCase(ScalyrTestCase):
    """
    Test class where we actually start the TCP server and also exercise the server processing
    pipeline and not just request parsing.
    """

    def test_plaintext_server_start_actual_server_parse_request_success(self):
        mock_logger = mock.Mock()
        mock_port = random.randint(5000, 65000)
        monitor_config = {
            "module": "graphite_monitor",
            "accept_plaintext": True,
            "buffer_size": 8096,
            "max_request_size": 1024 * 4,
            "plaintext_port": mock_port,
        }
        monitor = GraphiteMonitor(monitor_config=monitor_config, logger=mock_logger)

        try:
            monitor.start()

            # Give server some time to start up
            time.sleep(1)

            mock_request_1 = b"custom.metric.data.number1 5 1603104000001"
            mock_request_2 = b"custom.metric.data.number2 5.2 1603104000002"

            self.assertEqual(mock_logger.emit_value.call_count, 0)
            self.assertEqual(mock_logger.warn.call_count, 0)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", mock_port))
            sock.send(mock_request_1 + b"\n")
            sock.send(mock_request_2 + b"\n")
            sock.close()

            # Give server some time to process the request
            time.sleep(1)

            self.assertEqual(mock_logger.warn.call_count, 0)
            self.assertEqual(mock_logger.emit_value.call_count, 2)
            mock_logger.emit_value.assert_any_call(
                "custom.metric.data.number1",
                5.0,
                extra_fields={"orig_time": 1603104000001.0},
            )
            mock_logger.emit_value.assert_any_call(
                "custom.metric.data.number2",
                5.2,
                extra_fields={"orig_time": 1603104000002.0},
            )
        finally:
            monitor.stop()

    def test_pickle_server_start_actual_server_parse_request_success(self):
        mock_logger = mock.Mock()
        mock_port = random.randint(5000, 65000)
        monitor_config = {
            "module": "graphite_monitor",
            "accept_plaintext": False,
            "accept_pickle": True,
            "buffer_size": 8096,
            "max_request_size": 1024 * 4,
            "pickle_port": mock_port,
        }
        monitor = GraphiteMonitor(monitor_config=monitor_config, logger=mock_logger)

        try:
            monitor.start()

            # Give server some time to start up
            time.sleep(1)

            mock_data = []
            mock_data.append(("system.loadavg_1min", (1603104000001, 10.1)))
            mock_data.append(("system.loadavg_5min", (1603104000002, 10.2)))
            mock_data.append(("system.loadavg_15min", (1603104000003, 10.3)))
            mock_request = pickle.dumps(mock_data, 1)
            mock_request_size = compat.struct_pack_unicode("!L", len(mock_request))

            self.assertEqual(mock_logger.emit_value.call_count, 0)
            self.assertEqual(mock_logger.warn.call_count, 0)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", mock_port))
            sock.send(mock_request_size)
            sock.send(mock_request)
            sock.close()

            # Give server some time to process the request
            time.sleep(1)

            self.assertEqual(mock_logger.warn.call_count, 0)
            self.assertEqual(mock_logger.emit_value.call_count, 3)
            mock_logger.emit_value.assert_any_call(
                "system.loadavg_1min",
                10.1,
                extra_fields={"orig_time": 1603104000001.0},
            )
            mock_logger.emit_value.assert_any_call(
                "system.loadavg_5min",
                10.2,
                extra_fields={"orig_time": 1603104000002.0},
            )
            mock_logger.emit_value.assert_any_call(
                "system.loadavg_15min",
                10.3,
                extra_fields={"orig_time": 1603104000003.0},
            )
        finally:
            monitor.stop()


class GraphiteMonitorTextServerTestCase(ScalyrTestCase):
    """
    Test cases whre we don't start actual TCP server but just exercise the request / data parsing
    code.
    """

    def test_execute_request_mock_logger_success(self):
        mock_logger = mock.Mock()
        server = GraphiteTextServer(
            only_accept_local=True,
            port=5899,
            run_state=None,
            buffer_size=1024,
            max_request_size=1024 * 5,
            max_connection_idle_time=10,
            logger=mock_logger,
        )

        # 1. Unicode request data type
        mock_request = "custom.metric.data.number1 5 1603104000001"
        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)

        server.execute_request(request=mock_request)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 1)
        mock_logger.emit_value.assert_called_with(
            "custom.metric.data.number1",
            5.0,
            extra_fields={"orig_time": 1603104000001.0},
        )

        # 2. Bytes request data type
        mock_logger.reset_mock()

        mock_request = b"custom.metric.data.number2 6.2 1603104000002"
        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)

        server.execute_request(request=mock_request)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 1)
        mock_logger.emit_value.assert_called_with(
            "custom.metric.data.number2",
            6.2,
            extra_fields={"orig_time": 1603104000002.0},
        )


class GraphiteMonitorPickleServerTestCase(ScalyrTestCase):
    """
    Test cases whre we don't start actual TCP server but just exercise the request / data parsing
    code.
    """

    def test_execute_request_mock_logger_success(self):
        mock_logger = mock.Mock()
        server = GraphitePickleServer(
            only_accept_local=True,
            port=5899,
            run_state=None,
            buffer_size=1024,
            max_request_size=1024 * 5,
            max_connection_idle_time=10,
            logger=mock_logger,
        )

        mock_data = []
        mock_data.append(("system.loadavg_1min", (1603104000001, 10.1)))
        mock_data.append(("system.loadavg_5min", (1603104000002, 10.2)))
        mock_data.append(("system.loadavg_15min", (1603104000003, 10.3)))
        mock_request = pickle.dumps(mock_data, 1)

        self.assertEqual(mock_logger.emit_value.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)

        server.execute_request(request=mock_request)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 3)
        mock_logger.emit_value.assert_any_call(
            "system.loadavg_1min",
            10.1,
            extra_fields={"orig_time": 1603104000001.0},
        )
        mock_logger.emit_value.assert_any_call(
            "system.loadavg_5min",
            10.2,
            extra_fields={"orig_time": 1603104000002.0},
        )
        mock_logger.emit_value.assert_any_call(
            "system.loadavg_15min",
            10.3,
            extra_fields={"orig_time": 1603104000003.0},
        )
