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
import copy
import json

from io import open

import mock

from scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor import (
    KubernetesOpenMetricsMonitor,
    SCALYR_AGENT_ANNOTATION_SCRAPE_ENABLE,
    PROMETHEUS_ANNOTATION_SCAPE_PATH,
)
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.monitors_manager import set_monitors_manager
from scalyr_agent.test_base import ScalyrTestCase

__all__ = ["KubernetesOpenMetricsMonitorTestCase"]

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(BASE_DIR, "../fixtures/kubernetes_openmetrics_responses")

MOCK_AGENT_LOG_PATH = os.path.join("/data", "agent")

MOCK_CHECK_CONNECTIVITY = mock.Mock()
MOCK_CHECK_CONNECTIVITY.status_code = 200

with open(os.path.join(FIXTURES_DIR, "kubelet_pods_1.json"), "r") as fp:
    MOCK_KUBELET_QUERY_PODS_RESPONSE = json.loads(fp.read())

MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ANNOTATIONS = copy.deepcopy(
    MOCK_KUBELET_QUERY_PODS_RESPONSE
)
for pod in MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ANNOTATIONS["items"]:
    if SCALYR_AGENT_ANNOTATION_SCRAPE_ENABLE in pod["metadata"]["annotations"]:
        pod["metadata"]["annotations"][SCALYR_AGENT_ANNOTATION_SCRAPE_ENABLE] = "false"

MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ARM_EXPORTER = copy.deepcopy(
    MOCK_KUBELET_QUERY_PODS_RESPONSE
)
for index, pod in enumerate(MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ARM_EXPORTER["items"]):
    if pod["metadata"]["name"] == "arm-exporter-sv7rk":
        break
MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ARM_EXPORTER["items"].pop(index)

MOCK_KUBELET_QUERY_PODS_RESPONSE_ARM_EXPORTER_NEW_PATH = copy.deepcopy(
    MOCK_KUBELET_QUERY_PODS_RESPONSE
)
for index, pod in enumerate(
    MOCK_KUBELET_QUERY_PODS_RESPONSE_ARM_EXPORTER_NEW_PATH["items"]
):
    if pod["metadata"]["name"] == "arm-exporter-sv7rk":
        pod["metadata"]["annotations"][
            PROMETHEUS_ANNOTATION_SCAPE_PATH
        ] = "/test/new/path"


class KubernetesOpenMetricsMonitorTestCase(ScalyrTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SCALYR_K8S_NODE_NAME"] = "test-node-name"

    @classmethod
    def tearDownClass(cls):
        if "SCALYR_K8S_NODE_NAME" in os.environ:
            del os.environ["SCALYR_K8S_NODE_NAME"]

    def test_logger_include_node_name_config_option(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )
        self.assertEqual(
            monitor._logger.name,
            "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor(test-node-name)",
        )

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "logger_include_node_name": False,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )
        self.assertTrue(isinstance(monitor._logger.name, mock.Mock))

    def test_get_monitor_and_log_config(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        kwargs = {
            "monitor_id": "one",
            "url": "https://192.168.100.0:8080/metrics",
            "sample_interval": 10,
            "log_filename": "foo.log",
            "verify_https": False,
            "ca_file": None,
            "headers": None,
            "include_node_name": True,
        }
        (
            monitor_config,
            log_config,
        ) = monitor._KubernetesOpenMetricsMonitor__get_monitor_config_and_log_config(
            **kwargs
        )
        expected_monitor_config = {
            "ca_file": None,
            "extra_fields": JsonObject({"node": "test-node-name"}),
            "headers": JsonObject({}),
            "id": "one",
            "log_path": "scalyr_agent.builtin_monitors.openmetrics_monitor.log",
            "metric_component_value_include_list": JsonObject({}),
            "metric_name_exclude_list": [],
            "metric_name_include_list": ["*"],
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "sample_interval": 10,
            "timeout": 10,
            "url": "https://192.168.100.0:8080/metrics",
            "verify_https": False,
        }
        self.assertEqual(dict(monitor_config), dict(expected_monitor_config))
        self.assertEqual(
            log_config, {"path": os.path.join(MOCK_AGENT_LOG_PATH, "foo.log")}
        )

    def test_schedule_static_monitors_static_monitors_disabled(self):
        # 1. Static monitors are disabled
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "scrape_kubernetes_api_metrics": False,
            "scrape_kubernetes_api_cadvisor_metrics": False,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        mock_k8s = mock.Mock()
        mock_kubelet = mock.Mock()
        mock_kubelet.query_pods = mock.Mock(return_value={})

        monitor._k8s = mock_k8s
        monitor._kubelet = mock_kubelet

        self.assertFalse(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            monitor._KubernetesOpenMetricsMonitor__static_running_monitors, []
        )
        self.assertEqual(monitor._KubernetesOpenMetricsMonitor__running_monitors, {})

    def test_schedule_static_monitors_static_monitors_enabled(self):
        # Static monitors are enabled
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "scrape_kubernetes_api_metrics": True,
            "scrape_kubernetes_api_cadvisor_metrics": True,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        mock_log_watcher = mock.Mock()
        monitor.set_log_watcher(mock_log_watcher)
        monitor._KubernetesOpenMetricsMonitor__get_node_name = mock.Mock(
            return_value="node1"
        )

        mock_monitors_manager = mock.Mock()
        mock_monitors_manager.add_monitor().check_connectivity().status_code = 200
        set_monitors_manager(mock_monitors_manager)

        mock_k8s = mock.Mock()
        mock_kubelet = mock.Mock()
        mock_kubelet.query_pods = mock.Mock(return_value={})

        monitor._k8s = mock_k8s
        monitor._kubelet = mock_kubelet
        self.assertFalse(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs, {})
        self.assertEqual(mock_log_watcher.add_log_config.call_count, 0)
        # First mock call is empty and happen due to the connectivity checks
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 1)

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 2
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 0
        )
        self.assertEqual(mock_log_watcher.add_log_config.call_count, 2)
        # First mock call is empty and happen due to the connectivity checks
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 3)

        mock_log_watcher.add_log_config.assert_any_call(
            force_add=True,
            log_config={
                "parser": "agent-metrics",
                "path": os.path.join(
                    MOCK_AGENT_LOG_PATH,
                    "openmetrics_monitor-node1-kubernetes-api-metrics.log",
                ),
            },
            monitor_name="openmetrics_monitor",
        )
        mock_log_watcher.add_log_config.assert_any_call(
            force_add=True,
            log_config={
                "parser": "agent-metrics",
                "path": os.path.join(
                    MOCK_AGENT_LOG_PATH,
                    "openmetrics_monitor-node1-kubernetes-api-cadvisor-metrics.log",
                ),
            },
            monitor_name="openmetrics_monitor",
        )

        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[1][1]["monitor_config"][
                "id"
            ],
            "node1_kubernetes-api-metrics",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "id"
            ],
            "node1_kubernetes-api-cadvisor-metrics",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[1][1]["log_config"][
                "path"
            ],
            os.path.join(
                MOCK_AGENT_LOG_PATH,
                "openmetrics_monitor-node1-kubernetes-api-metrics.log",
            ),
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["log_config"][
                "path"
            ],
            os.path.join(
                MOCK_AGENT_LOG_PATH,
                "openmetrics_monitor-node1-kubernetes-api-cadvisor-metrics.log",
            ),
        )

    def test_schedule_dynamic_monitors_no_pods_found(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "scrape_kubernetes_api_metrics": False,
            "scrape_kubernetes_api_cadvisor_metrics": False,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        mock_log_watcher = mock.Mock()
        monitor.set_log_watcher(mock_log_watcher)
        monitor._KubernetesOpenMetricsMonitor__get_node_name = mock.Mock(
            return_value="node1"
        )

        mock_monitors_manager = mock.Mock()
        mock_monitors_manager.add_monitor().check_connectivity().status_code = 200
        set_monitors_manager(mock_monitors_manager)

        mock_k8s = mock.Mock()
        mock_kubelet = mock.Mock()
        mock_kubelet.query_pods = mock.Mock(return_value={})

        monitor._k8s = mock_k8s
        monitor._kubelet = mock_kubelet

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 0
        )
        self.assertEqual(mock_log_watcher.add_log_config.call_count, 0)
        # First mock call is empty and happen due to the connectivity checks
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 1)

    def test_schedule_dynamic_monitors_no_matching_pods_found(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "scrape_kubernetes_api_metrics": False,
            "scrape_kubernetes_api_cadvisor_metrics": False,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        mock_log_watcher = mock.Mock()
        monitor.set_log_watcher(mock_log_watcher)
        monitor._KubernetesOpenMetricsMonitor__get_node_name = mock.Mock(
            return_value="node1"
        )

        mock_add_monitor = mock.Mock()
        mock_add_monitor.check_connectivity().status_code = 200

        mock_monitors_manager = mock.Mock()
        mock_monitors_manager.add_monitor = mock_add_monitor
        set_monitors_manager(mock_monitors_manager)

        mock_k8s = mock.Mock()
        mock_kubelet = mock.Mock()
        mock_kubelet.query_pods = mock.Mock(
            return_value=MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ANNOTATIONS
        )

        monitor._k8s = mock_k8s
        monitor._kubelet = mock_kubelet

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 0
        )
        self.assertEqual(mock_log_watcher.add_log_config.call_count, 0)
        # First mock call is empty and happen due to the connectivity checks
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 0)

    def test_schedule_dynamic_monitors_matching_pods_found(self):
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor",
            "scrape_kubernetes_api_metrics": False,
            "scrape_kubernetes_api_cadvisor_metrics": False,
        }
        global_config = mock.Mock()
        global_config.agent_log_path = MOCK_AGENT_LOG_PATH
        mock_logger = mock.Mock()

        monitor = KubernetesOpenMetricsMonitor(
            monitor_config=monitor_config,
            logger=mock_logger,
            global_config=global_config,
        )

        def mock_add_log_config_func(force_add, log_config, monitor_name):
            mock_config = {"path": log_config["path"]}
            return mock_config

        def mock_add_monitor_func(monitor_config, log_config, global_config):
            mock_monitor = mock.Mock()
            mock_monitor.uid = f"{monitor_config['module']}-{monitor_config['id']}"
            return mock_monitor

        mock_log_watcher = mock.Mock()
        mock_log_watcher.add_log_config.side_effect = mock_add_log_config_func
        monitor.set_log_watcher(mock_log_watcher)

        monitor._KubernetesOpenMetricsMonitor__get_node_name = mock.Mock(
            return_value="node1"
        )

        mock_monitors_manager = mock.Mock()

        mock_add_monitor = mock.Mock()
        mock_add_monitor.side_effect = mock_add_monitor_func
        mock_add_monitor.check_connectivity().status_code = 200

        mock_monitors_manager.add_monitor = mock_add_monitor
        set_monitors_manager(mock_monitors_manager)

        mock_k8s = mock.Mock()
        mock_kubelet = mock.Mock()
        mock_kubelet.query_pods = mock.Mock(
            return_value=MOCK_KUBELET_QUERY_PODS_RESPONSE
        )

        monitor._k8s = mock_k8s
        monitor._kubelet = mock_kubelet

        # 1. First gather sample call, 3 new matching pods should be found
        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 3
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 3
        )
        self.assertEqual(mock_log_watcher.add_log_config.call_count, 3)
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 3)
        self.assertEqual(mock_monitors_manager.remove_monitor.call_count, 0)

        mock_log_watcher.add_log_config.assert_any_call(
            force_add=True,
            log_config={
                "parser": "agent-metrics",
                "path": os.path.join(
                    MOCK_AGENT_LOG_PATH,
                    "openmetrics_monitor-node1-java-hello-world-7596684fcd-jwqcp.log",
                ),
            },
            monitor_name="openmetrics_monitor",
        )
        mock_log_watcher.add_log_config.assert_any_call(
            force_add=True,
            log_config={
                "parser": "agent-metrics",
                "path": os.path.join(
                    MOCK_AGENT_LOG_PATH,
                    "openmetrics_monitor-node1-arm-exporter-sv7rk.log",
                ),
            },
            monitor_name="openmetrics_monitor",
        )
        mock_log_watcher.add_log_config.assert_any_call(
            force_add=True,
            log_config={
                "parser": "agent-metrics",
                "path": os.path.join(
                    MOCK_AGENT_LOG_PATH,
                    "openmetrics_monitor-node1-node-exporter-bhhvk.log",
                ),
            },
            monitor_name="openmetrics_monitor",
        )

        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[0][1]["monitor_config"][
                "id"
            ],
            "node1_node-exporter-bhhvk",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[0][1]["monitor_config"][
                "url"
            ],
            "http://10.5.5.5.141:9100/metrics",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[1][1]["monitor_config"][
                "id"
            ],
            "node1_arm-exporter-sv7rk",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[1][1]["monitor_config"][
                "url"
            ],
            "http://10.5.5.5.141:9243/metrics",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "id"
            ],
            "node1_java-hello-world-7596684fcd-jwqcp",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "url"
            ],
            "https://10.5.5.5.141:9404/metrics1",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "sample_interval"
            ],
            120,
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "timeout"
            ],
            5,
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "verify_https"
            ],
            False,
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "metric_name_include_list"
            ],
            ["include1", "include2"],
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[2][1]["monitor_config"][
                "metric_name_exclude_list"
            ],
            ["exclude1", "exclude2"],
        )

        # 2. Second gather call, single pod (arm exporter) has gonne away so 1 dynamic monitor should be removed
        mock_kubelet.query_pods = mock.Mock(
            return_value=MOCK_KUBELET_QUERY_PODS_RESPONSE_NO_ARM_EXPORTER
        )

        mock_log_watcher.reset_mock()
        mock_add_monitor.reset_mock()
        mock_monitors_manager.remove_monitor.reset_mock()

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 2
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 2
        )
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 0)
        self.assertEqual(mock_monitors_manager.remove_monitor.call_count, 1)

        mock_monitors_manager.remove_monitor.assert_called_with(
            "scalyr_agent.builtin_monitors.openmetrics_monitor-node1_arm-exporter-sv7rk"
        )

        # 3. Pod comes back but with different scrape url
        mock_kubelet.query_pods = mock.Mock(
            return_value=MOCK_KUBELET_QUERY_PODS_RESPONSE_ARM_EXPORTER_NEW_PATH
        )

        mock_log_watcher.reset_mock()
        mock_add_monitor.reset_mock()
        mock_monitors_manager.remove_monitor.reset_mock()

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 3
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 3
        )
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 1)
        self.assertEqual(mock_monitors_manager.remove_monitor.call_count, 0)

        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[0][1]["monitor_config"][
                "id"
            ],
            "node1_arm-exporter-sv7rk",
        )
        self.assertEqual(
            mock_monitors_manager.add_monitor.call_args_list[0][1]["monitor_config"][
                "url"
            ],
            "http://10.5.5.5.141:9243/test/new/path",
        )

        # 4. And now API returns no pods which means all the monitors should be removed
        mock_kubelet.query_pods = mock.Mock(return_value={})

        mock_log_watcher.reset_mock()
        mock_add_monitor.reset_mock()
        mock_monitors_manager.remove_monitor.reset_mock()

        monitor.gather_sample()
        self.assertTrue(monitor._KubernetesOpenMetricsMonitor__static_monitors_started)
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__static_running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__running_monitors), 0
        )
        self.assertEqual(
            len(monitor._KubernetesOpenMetricsMonitor__watcher_log_configs), 0
        )
        self.assertEqual(mock_monitors_manager.add_monitor.call_count, 0)
        self.assertEqual(mock_monitors_manager.remove_monitor.call_count, 3)

        mock_monitors_manager.remove_monitor.assert_any_call(
            "scalyr_agent.builtin_monitors.openmetrics_monitor-node1_java-hello-world-7596684fcd-jwqcp"
        )
        mock_monitors_manager.remove_monitor.assert_any_call(
            "scalyr_agent.builtin_monitors.openmetrics_monitor-node1_node-exporter-bhhvk"
        )
        mock_monitors_manager.remove_monitor.assert_any_call(
            "scalyr_agent.builtin_monitors.openmetrics_monitor-node1_arm-exporter-sv7rk"
        )
