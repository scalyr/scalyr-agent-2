# Copyright 2014-2021 Scalyr Inc.
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

from __future__ import absolute_import

import os
import unittest

import mock
import requests_mock

from scalyr_agent.builtin_monitors.openmetrics_monitor import OpenMetricsMonitor

__all__ = ["OpenMetricsMonitorTestCase"]

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(BASE_DIR, "../fixtures/openmetrics_responses")

MOCK_URL = "https://my.host:8080/metrics"

MOCK_RESPONSE_HEADERS_TEXT = {
    "Content-Type": "application/openmetrics-text; version=1.0.0; charset=utf-8",
}

MOCK_RESPONSE_HEADERS_PROTOBUF = {
    "Content-Type": "application/openmetrics-protobuf; version=1.0.0; charset=utf-8",
}

# TODO: Use fixture files with acutal responses
MOCK_DATA_1 = """
http_requests_total{method="post",code="400"}  3   1395066363000
some.metric.name1 1555
some.metric.name2 1556 123456789

# HELP metric_name Description of the metric
# TYPE metric_name type
# Comment that's not parsed by prometheus
http_requests_total{method="post",code="400"}  4   1395066363001

traefik_entrypoint_request_duration_seconds_count{code="404",entrypoint="traefik",method="GET",protocol="http"} 44
"""

MOCK_DATA_2 = """
# TYPE http_requests_total histogram
http_requests_total{method="post",code="400"}  3   1395066363000
some.metric.name1 1555
some.metric.name2 1556 123456789

# HELP metric_name Description of the metric
# TYPE metric_name type
# Comment that's not parsed by prometheus
# TYPE http_requests_total summary
http_requests_total{method="post",code="400"}  4   1395066363001

# TYPE traefik_entrypoint_request_duration_seconds_count summary
traefik_entrypoint_request_duration_seconds_count{code="404",entrypoint="traefik",method="GET",protocol="http"} 44
"""

with open(os.path.join(FIXTURES_DIR, "jmx_exporter_kafka.txt"), "r") as fp:
    MOCK_DATA_3 = fp.read()


class OpenMetricsMonitorTestCase(unittest.TestCase):
    @requests_mock.Mocker()
    def test_gather_sample_success_mock_data_1(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 5)

        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            3,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363000},
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name1", 1555, extra_fields={}
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2", 1556, extra_fields={"timestamp": 123456789}
        )
        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            4,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363001},
        )
        mock_logger.emit_value.assert_any_call(
            "traefik_entrypoint_request_duration_seconds_count",
            44,
            extra_fields={
                "code": "404",
                "entrypoint": "traefik",
                "method": "GET",
                "protocol": "http",
            },
        )

    @requests_mock.Mocker()
    def test_gather_sample_success_mock_data_jmx_exporter_kafka(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_3, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 6)

        mock_logger.emit_value.assert_any_call(
            "kafka_server_replicafetchermanager_minfetchrate",
            0.0,
            extra_fields={"clientId": "Replica"},
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_network_requestmetrics_totaltimems",
            1.0,
            extra_fields={"request": "JoinGroup"},
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_network_requestmetrics_totaltimems",
            0.1,
            extra_fields={"request": "GroupCoordinator"},
        )

    @requests_mock.Mocker()
    def test_gather_sample_non_200_response(self, m):
        m.get(MOCK_URL, text="bar", status_code=404, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        mock_logger.warn.assert_called_with(
            "Failed to fetch metrics from https://my.host:8080/metrics: status_code=404,body=bar"
        )
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 1)
        self.assertEqual(mock_logger.emit_value.call_count, 0)

    @requests_mock.Mocker()
    def test_gather_sample_ignored_metric_names(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_whitelist": ["some.*", "traefik*"],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 3)

        mock_logger.emit_value.assert_any_call(
            "some.metric.name1", 1555, extra_fields={}
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2", 1556, extra_fields={"timestamp": 123456789}
        )
        mock_logger.emit_value.assert_any_call(
            "traefik_entrypoint_request_duration_seconds_count",
            44,
            extra_fields={
                "code": "404",
                "entrypoint": "traefik",
                "method": "GET",
                "protocol": "http",
            },
        )

    @requests_mock.Mocker()
    def test_gather_sample_non_supported_metric_types(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_2, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 3)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 2)

        mock_logger.emit_value.assert_any_call(
            "some.metric.name1", 1555, extra_fields={}
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2", 1556, extra_fields={"timestamp": 123456789}
        )

    @requests_mock.Mocker()
    def test_gather_sample_non_supported_protobuf_format(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_PROTOBUF)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 1)
        self.assertEqual(mock_logger.emit_value.call_count, 0)
