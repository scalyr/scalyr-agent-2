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

from __future__ import absolute_import

import os

from io import open

import six
import mock
import requests_mock

from scalyr_agent.json_lib import JsonObject
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.builtin_monitors.openmetrics_monitor import OpenMetricsMonitor
from scalyr_agent.test_base import ScalyrTestCase

__all__ = ["OpenMetricsMonitorTestCase"]

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(BASE_DIR, "../fixtures/openmetrics_responses")

MOCK_URL = six.text_type("https://my.host:8080/metrics")

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

with open(os.path.join(FIXTURES_DIR, "jmx_exporter_kafka_2.txt"), "r") as fp:
    MOCK_DATA_4 = fp.read()

with open(os.path.join(FIXTURES_DIR, "jmx_exporter_zookeeper_1.txt"), "r") as fp:
    MOCK_DATA_5 = fp.read()


MOCK_TIMESTAMP_S = 123456789
MOCK_TIMESTAMP_MS = MOCK_TIMESTAMP_S * 1000


class OpenMetricsMonitorTestCase(ScalyrTestCase):
    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
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
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name1",
            1555,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2",
            1556,
            extra_fields={"timestamp": 123456789},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            4,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363001},
            timestamp=MOCK_TIMESTAMP_MS,
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
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_success_mock_data_1_extra_fields(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "extra_fields": JsonObject({"foo1": "bar1", "foo2": "bar2"}),
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
            extra_fields={
                "method": "post",
                "code": "400",
                "timestamp": 1395066363000,
                "foo1": "bar1",
                "foo2": "bar2",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name1",
            1555,
            extra_fields={"foo1": "bar1", "foo2": "bar2"},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2",
            1556,
            extra_fields={"timestamp": 123456789, "foo1": "bar1", "foo2": "bar2"},
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    def test_gather_sample_success_mock_data_1_additional_request_kwargs(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "timeout": 1,
            "ca_file": "/tmp/cafile",
            "verify_https": True,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)

        request_kwargs = monitor._get_request_kwargs(url="https://fooo")
        self.assertEqual(request_kwargs, {"verify": "/tmp/cafile"})

        request_kwargs = monitor._get_request_kwargs(url="http://fooo")
        self.assertEqual(request_kwargs, {})

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "timeout": 1,
            "verify_https": True,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)

        request_kwargs = monitor._get_request_kwargs(url="https://fooo")
        self.assertEqual(
            request_kwargs,
            {
                "verify": True,
            },
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_success_mock_data_jmx_exporter_kafka_1(self, m):
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
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_network_requestmetrics_totaltimems",
            1.0,
            extra_fields={"request": "JoinGroup"},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_network_requestmetrics_totaltimems",
            0.1,
            extra_fields={"request": "GroupCoordinator"},
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_success_mock_data_jmx_exporter_kafka_2(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_4, headers=MOCK_RESPONSE_HEADERS_TEXT)

        # 1. No filters
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 20)
        self.assertEqual(mock_logger.emit_value.call_count, 4900)

        mock_logger.warn.assert_any_call(
            'Failed to cast metric "kafka_server_socketservermetrics_reauthentication_latency_avg" value "NaN" to int: invalid literal for int() with base 10: \'NaN\''
        )
        mock_logger.warn.assert_called_with(
            'Parsed more than 2000 metrics (4900) for URL https://my.host:8080/metrics. You are strongly encouraged to filter metrics at the source or set "metric_name_exclude_list" monitor configuration option to avoid excessive number of metrics being ingested.',
            limit_once_per_x_secs=86400,
            limit_key="max-metrics-https://my.host:8080/metrics",
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_server_socketservermetrics_io_wait_ratio",
            0.468470646634658,
            extra_fields={
                "listener": "EXTERNAL",
                "network_processor": "3",
                "timestamp": 123456789,
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_network_socketserver_memorypoolavailable",
            9.223372036854776e18,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_log_log_logstartoffset",
            340,
            extra_fields={
                "topic": "sample-streams-KSTREAM-AGGREGATE-STATE-STORE-0000000002-repartition",
                "partition": "0",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )

        # 2. All metrics are excluded - warning should be emitted
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 20)
        self.assertEqual(mock_logger.emit_value.call_count, 0)

        mock_logger.warn.assert_called_with(
            "Server returned 4900 metrics, but none were included. This likely means that filters specified as part of the plugin configuration are too restrictive and need to be relaxed.",
            limit_once_per_x_secs=86400,
            limit_key="no-metrics-https://my.host:8080/metrics",
        )

        # 3. Metric extra_field filters
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [],
            "metric_component_value_include_list": JsonObject(
                {
                    "kafka_log_log_numlogsegments": {
                        "topic": [six.text_type("connect-status")]
                    },
                    "kafka_server_fetcherlagmetrics_consumerlag": {
                        "topic": [six.text_type("connect-status")]
                    },
                    "kafka_log_log_logstartoffset": {
                        "topic": [six.text_type("connect-status")]
                    },
                    "kafka_cluster_partition_underreplicated": {
                        "topic": [six.text_type("connect-status")]
                    },
                }
            ),
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 19)
        self.assertEqual(mock_logger.emit_value.call_count, 20)

        mock_logger.emit_value.assert_any_call(
            "kafka_cluster_partition_underreplicated",
            0.0,
            extra_fields={
                "topic": "connect-status",
                "partition": "0",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_server_fetcherlagmetrics_consumerlag",
            0.0,
            extra_fields={
                "clientid": "ReplicaFetcherThread-0-3",
                "partition": "0",
                "topic": "connect-status",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "kafka_log_log_numlogsegments",
            1.0,
            extra_fields={"topic": "connect-status", "partition": "0"},
            timestamp=MOCK_TIMESTAMP_MS,
        )

        mock_logger.emit_value.assert_any_call(
            "kafka_log_log_logstartoffset",
            0.0,
            extra_fields={"topic": "connect-status", "partition": "3"},
            timestamp=MOCK_TIMESTAMP_MS,
        )

        # 4. Metric extra_field filters (matches any metric name)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [],
            "metric_component_value_include_list": JsonObject(
                {
                    "*": {"topic": [six.text_type("connect-status")]},
                }
            ),
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 19)
        self.assertEqual(mock_logger.emit_value.call_count, 55)

        for call in mock_logger.emit_value.call_args_list:
            call_kwargs = call[1]
            self.assertEqual(call_kwargs["extra_fields"]["topic"], "connect-status")

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_success_mock_data_jmx_exporter_zookeeper_1(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_5, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 144)

        mock_logger.emit_value.assert_any_call(
            "zookeeper_electiontype",
            3.0,
            extra_fields={
                "replicaid": "2",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "zookeeper_leader",
            1.0,
            extra_fields={
                "replicaid": "3",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "zookeeper_leader",
            0.0,
            extra_fields={
                "replicaid": "2",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "zookeeper_requeststalelatencycheck",
            0.0,
            extra_fields={"membertype": "Follower", "replicaid": "2"},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "jvm_info",
            1.0,
            extra_fields={
                "version": "11.0.13+8-LTS",
                "vendor": "Azul Systems, Inc.",
                "runtime": "OpenJDK Runtime Environment",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "jvm_memory_pool_bytes_used",
            5714432.0,
            extra_fields={
                "pool": "CodeHeap 'profiled nmethods'",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "jvm_memory_pool_bytes_used",
            2519520.0,
            extra_fields={
                "pool": "Compressed Class Space",
            },
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "jvm_bar_1",
            1.8446744073709552e19,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "jvm_bar_2",
            6e08,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
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
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_metric_name_include_list(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 3)

        mock_logger.emit_value.assert_any_call(
            "some.metric.name1",
            1555,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2",
            1556,
            extra_fields={"timestamp": 123456789},
            timestamp=MOCK_TIMESTAMP_MS,
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
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_metric_name_exclude_list(self, m):
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_exclude_list": [
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 2)

        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            3,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363000},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            4,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363001},
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
    def test_gather_sample_metric_name_include_list_and_exclude_list(self, m):
        # Both exclude_list and include_list options are specified, but exclude_list has higher priority
        m.get(MOCK_URL, text=MOCK_DATA_1, headers=MOCK_RESPONSE_HEADERS_TEXT)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
            "metric_name_exclude_list": [
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 1)
        self.assertEqual(mock_logger.emit_value.call_count, 0)

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_name_include_list": [
                six.text_type("http_*"),
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
            "metric_name_exclude_list": [
                six.text_type("some.*"),
                six.text_type("traefik*"),
            ],
        }
        mock_logger = mock.Mock()
        monitor = OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
        monitor.gather_sample()
        self.assertEqual(mock_logger.debug.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, 2)

        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            3,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363000},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "http_requests_total",
            4,
            extra_fields={"method": "post", "code": "400", "timestamp": 1395066363001},
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
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
            "some.metric.name1",
            1555,
            extra_fields={},
            timestamp=MOCK_TIMESTAMP_MS,
        )
        mock_logger.emit_value.assert_any_call(
            "some.metric.name2",
            1556,
            extra_fields={"timestamp": 123456789},
            timestamp=MOCK_TIMESTAMP_MS,
        )

    @requests_mock.Mocker()
    @mock.patch("time.time", mock.MagicMock(return_value=MOCK_TIMESTAMP_S))
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

    def test_metric_component_value_include_list_config_option_value(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_component_value_include_list": ["foo"],
        }
        mock_logger = mock.Mock()
        self.assertRaisesRegexp(
            BadMonitorConfiguration,
            "Prohibited conversion",
            OpenMetricsMonitor,
            monitor_config=monitor_config,
            logger=mock_logger,
        )

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_component_value_include_list": JsonObject({"metric": "bar"}),
        }
        mock_logger = mock.Mock()
        self.assertRaisesRegexp(
            BadMonitorConfiguration,
            "Value must be a dictionary",
            OpenMetricsMonitor,
            monitor_config=monitor_config,
            logger=mock_logger,
        )

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_component_value_include_list": JsonObject(
                {"metric": {"component": "bar"}}
            ),
        }
        mock_logger = mock.Mock()
        self.assertRaisesRegexp(
            BadMonitorConfiguration,
            "Value must be a list of strings",
            OpenMetricsMonitor,
            monitor_config=monitor_config,
            logger=mock_logger,
        )

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_component_value_include_list": JsonObject(
                {"metric": {"component": [1, 2]}}
            ),
        }
        mock_logger = mock.Mock()
        self.assertRaisesRegexp(
            BadMonitorConfiguration,
            "Value must be a list of strings",
            OpenMetricsMonitor,
            monitor_config=monitor_config,
            logger=mock_logger,
        )

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "url": MOCK_URL,
            "metric_component_value_include_list": JsonObject(
                {"metric": {"component": [six.text_type("value")]}}
            ),
        }
        mock_logger = mock.Mock()
        OpenMetricsMonitor(monitor_config=monitor_config, logger=mock_logger)
