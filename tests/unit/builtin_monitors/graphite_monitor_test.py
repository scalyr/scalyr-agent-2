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

import pickle

from scalyr_agent.builtin_monitors.graphite_monitor import GraphiteTextServer
from scalyr_agent.builtin_monitors.graphite_monitor import GraphitePickleServer
from scalyr_agent.scalyr_logging import AgentLogger
from scalyr_agent.test_base import ScalyrTestCase

import mock

__all__ = ["GraphiteMonitorTextServerTestCase", "GraphiteMonitorPickleServerTestCase"]


class GraphiteMonitorTextServerTestCase(ScalyrTestCase):
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
