# Copyright 2021 Scalyr Inc.
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

"""
Monitor which scrapes metrics from OpenMetrics / Prometheus metrics endpoints from metrics exporter
running as pods in a Kubernetes cluster.

This monitor is designed to run on an agent which is deployed as a DaemonSet on a Kubernetes
cluster. If you to scrape metrics in a OpenMetrics format from a static endpoint, you can use
"scalyr_agent.builtin_monitors.openmetrics_monitor" monitor.

It works by automatically discovering all the metrics exporter endpoints which are exposed on the
node the agent is running on.

It finds matching exporters by querying the Kubernetes API for pods which match special annotations.

If a pod contains the following annotations, it will be automatically discovered and scraped by this
monitor:

    * ``k8s.monitor.config.scalyr.com/scrape`` (required) - Set this value to "true" to enable metrics scraping
      for a specific pod.
    * ``prometheus.io/port`` (required) - Tells agent which port on the node to use when scraping metrics.
      Actual pod IP address is automatically discovered.
    * ``prometheus.io/scheme`` (optional, defaults to http) - Tells agent which protocol to use when
      building scrapper URL. Valid values are http and https.
    * ``prometheus.io/path`` (optional, defaults to /metrics) - Tells agent which request path to use when
      building scrapper URL.
    * ``k8s.monitor.config.scalyr.com/scrape_interval`` (optional) - How often to scrape this endpoint.
      Defaults to 60 seconds.
    * ``k8s.monitor.config.scalyr.com/scrape_timeout`` (optional) - How long to wait before timing out.
    * ``k8s.monitor.config.scalyr.com/verify_https`` (optional) - Set to false to disable remote SSL
      cert and hostname validation.
    * ``k8s.monitor.config.scalyr.com/attributes`` (optional) - Optional JSON object with the attributes
      (key/value pairs) which get included with every metric. Template syntax is supported for attribute
      values. Right now only pod labels are available in the template context.
      scrape requests. Defaults to 10 seconds.
    * ``k8s.monitor.config.scalyr.com/metric_name_include_list`` (optional) - Comma delimited list
      of metric names to include when scraping.
    * ``k8s.monitor.config.scalyr.com/metric_name_exclude_list`` (optional) - Comma delimited list
      of metric names to exclude from scraping.
    * ``k8s.monitor.config.scalyr.com/calculate_rate_metric_names`` (optional) - Comma delimited list
      of metric names for which per-second rates should be calculated in the agent.

"prometheus.io/*" annotations are de-facto annotations used by various other Prometheus metrics
exporters auto discovery mechanisms.

Example below shows DaemonSet definition for node-exporter metrics exporter which defined needed label
for the exporter pod:

    ---
    apiVersion: apps/v1
    kind: DaemonSet
    metadata:
    labels:
        app.kubernetes.io/component: exporter
        app.kubernetes.io/name: node-exporter
    name: node-exporter
    namespace: monitoring
    spec:
    selector:
        matchLabels:
        app.kubernetes.io/component: exporter
        app.kubernetes.io/name: node-exporter
    template:
        metadata:
        labels:
            app.kubernetes.io/component: exporter
            app.kubernetes.io/name: node-exporter
        annotations:
            prometheus.io/scrape:                                     'true'
            prometheus.io/port:                                       '9100'
            k8s.monitor.config.scalyr.com/scrape:                     'true'
            k8s.monitor.config.scalyr.com/scrape_interval:            '120'
            k8s.monitor.config.scalyr.com/scrape_timeout:              '5'
            k8s.monitor.config.scalyr.com/attributes:                  '{"app": "${pod_labels_app}", "instance": "{pod_labels_app.kubernetes.io/instance}", "region": "eu"}'
            k8s.monitor.config.scalyr.com/calculate_rate_metric_names: 'docker.cpu_usage_total_seconds,docker.memory_usage_total'
        spec:
        containers:
        - args:
            - --path.sysfs=/host/sys
            - --path.rootfs=/host/root
            - --no-collector.wifi
            - --no-collector.hwmon
            - --collector.filesystem.ignored-mount-points=^/(dev|proc|sys|var/lib/docker/.+|var/lib/kubelet/pods/.+)($|/)
            - --collector.netclass.ignored-devices=^(veth.*)$
            name: node-exporter
            image: prom/node-exporter
            ports:
            - containerPort: 9100
                protocol: TCP
            resources:
            limits:
                cpu: 250m
                memory: 180Mi
            requests:
                cpu: 102m
                memory: 180Mi
            volumeMounts:
            - mountPath: /host/proc
            name: proc
            readOnly: false
            - mountPath: /host/sys
            name: sys
            readOnly: false
            - mountPath: /host/root
            mountPropagation: HostToContainer
            name: root
            readOnly: true
        nodeSelector:
            kubernetes.io/os: linux
        securityContext:
            runAsNonRoot: true
            runAsUser: 65534
        volumes:
        - hostPath:
            path: /proc
            name: proc
        - hostPath:
            path: /sys
            name: sys
        - hostPath:
            path: /
            name: root

In this example, agent will dynamically retrieve pod IP and scrape metrics from
http://<pod ip>:9100/metrics.

In addition to scrapping metrics from those dynamically discovered exporters, this monitor also
supports scraping system wide and cAdvisor metrics from Kuberntes API.

Those metrics are scraped from the following URLs:

* General Kubernetes API metrics - https://kubernetes.default.svc:443/api/v1/nodes/<node name>/proxy/metrics
* Kubernetes cAdvisor metrics - https://kubernetes.default.svc:443/api/v1/nodes/<node name>/proxy/metrics/cadvisor

Both of those endpoints return metrics which are specific to that node. If you want to view metrics
globally across the whole cluster, you will need to combine it on the server side using sum() and
similar.

Since those endpoints result in a lot of metrics per scrape (2000+) scraping is disabled by default
and can be enabled via monitor config options. This is especially true for general Kubernetes
API metrics endpoint which include response duration histograms and many other metrics for all the
API endpoints.

## How it works

# Notes, Limitations

This monitor will only work correctly if the agent is deployed as a DaemonSet. That's because each
monitor instance will only discover metrics endpoints which are local to the node the agent is
running on.
"""

from __future__ import absolute_import

from typing import Dict
from typing import List
from typing import Tuple
from typing import Any
from typing import Optional

import os
import re
import time

from string import Template
from dataclasses import dataclass

import six

from scalyr_agent import ScalyrMonitor
from scalyr_agent import define_config_option
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.util import json_decode
from scalyr_agent.monitors_manager import get_monitors_manager
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.monitor_utils.k8s import KubernetesApi
from scalyr_agent.monitor_utils.k8s import KubeletApi
from scalyr_agent import scalyr_logging
from scalyr_agent import compat

__monitor__ = __name__

# Default config option values
DEFAULT_SCRAPE_INTERVAL = 60.0
DEFAULT_SCRAPE_TIMEOUT = 10
DEFAULT_VERIFY_HTTPS = True

DEFAULT_KUBERNETES_API_METRICS_SCRAPE_INTERVAL = 60.0
DEFAULT_KUBERNETES_API_CADVISOR_METRICS_SCRAPE_INTERVAL = 60.0

DEFAULT_KUBERNETES_API_METRIC_NAME_INCLUDE_LIST = ["*"]
DEFAULT_KUBERNETES_API_METRIC_NAME_EXCLUDE_LIST = [
    # We exclude all the per request path metrics which provide little value and there are tons
    # of those (one per visited path + query params). This means that each scrape only returns
    # ~400 metrics instead of 2000+.
    # Exclude histograms
    "*_bucket",
    # Exclude per path and rest client stats (tons of metrics, one for every path and not so useful)
    "kubelet_http_*",
    "rest_client_*",
]

DEFAULT_KUBERNETES_API_CADVISOR_METRIC_NAME_INCLUDE_LIST = ["*"]
DEFAULT_KUBERNETES_API_CADVISOR_METRIC_NAME_EXCLUDE_LIST = []

# Default annotation values
DEFAULT_SCRAPE_SCHEME = "http"
DEFAULT_SCRAPE_PORT = None
DEFAULT_SCRAPE_PATH = "/metrics"

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor``",
    convert_to=six.text_type,
    required_option=True,
)

# Common Kubernetes monitors options
define_config_option(
    __monitor__,
    "k8s_kubelet_host_ip",
    "Optional (defaults to None). Defines the host IP address for the Kubelet API. If None, the Kubernetes API will be queried for it",
    convert_to=six.text_type,
    default=None,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_kubelet_api_url_template",
    "Optional (defaults to https://${host_ip}:10250). Defines the port and protocol to use when talking to the kubelet API. "
    "Allowed template variables are `node_name` and `host_ip`.",
    convert_to=six.text_type,
    default="https://${host_ip}:10250",
    env_aware=True,
)

# Monitor specific options
define_config_option(
    __monitor__,
    "verify_https",
    "Set to False to disable verification of the server certificate and hostname when scraping metrics from all the exporters.",
    convert_to=bool,
    default=DEFAULT_VERIFY_HTTPS,
)

define_config_option(
    __monitor__,
    "scrape_interval",
    "How often to scrape metrics from each of the dynamically discovered metric exporter endpoints. Defaults to 60 seconds. This can be overridden on per exporter basis using annotations.",
    convert_to=float,
    default=DEFAULT_SCRAPE_INTERVAL,
)

define_config_option(
    __monitor__,
    "scrape_timeout",
    "Timeout for scrape HTTP requests. Defaults to 10 seconds.",
    convert_to=int,
    default=DEFAULT_SCRAPE_TIMEOUT,
)

define_config_option(
    __monitor__,
    "scrape_kubernetes_api_metrics",
    "Set to True to enable scraping metrics from /metrics Kubernetes API endpoint.",
    convert_to=bool,
    default=False,
)

define_config_option(
    __monitor__,
    "scrape_kubernetes_api_cadvisor_metrics",
    "Set to True to enable scraping metrics from /metrics/cadvisor Kubernetes API endpoint.",
    convert_to=bool,
    default=False,
)

define_config_option(
    __monitor__,
    "kubernetes_api_metrics_scrape_interval",
    "How often to scrape metrics Kubernetes API /metrics endpoint. Defaults to 60 seconds.",
    convert_to=float,
    default=DEFAULT_KUBERNETES_API_METRICS_SCRAPE_INTERVAL,
)

define_config_option(
    __monitor__,
    "kubernetes_api_metric_name_include_list",
    "Optional metric name include list for Kubernetes API metrics endpoint. By default all metrics are included.",
    convert_to=ArrayOfStrings,
    default=DEFAULT_KUBERNETES_API_METRIC_NAME_INCLUDE_LIST,
)

define_config_option(
    __monitor__,
    "kubernetes_api_metric_name_exclude_list",
    'Optional metric name exclude list for Kubernetes API metrics endpoint. By default all the histogram and per HTTP path metrics are excluded. If you want to include all the metrics, set this value to "*".',
    convert_to=ArrayOfStrings,
    default=DEFAULT_KUBERNETES_API_METRIC_NAME_EXCLUDE_LIST,
)

define_config_option(
    __monitor__,
    "kubernetes_api_metric_component_value_include_list",
    "Optional include list filter for metric component values.",
    convert_to=JsonObject,
    default=JsonObject({}),
)

define_config_option(
    __monitor__,
    "kubernetes_api_cadvisor_metrics_scrape_interval",
    "How often to scrape metrics Kubernetes API /metrics/cadvisor endpoint. Defaults to 60 seconds.",
    convert_to=float,
    default=DEFAULT_KUBERNETES_API_CADVISOR_METRICS_SCRAPE_INTERVAL,
)

define_config_option(
    __monitor__,
    "kubernetes_api_cadvisor_metric_name_include_list",
    "Optional metric name include list for Kubernetes cAdvisor API metrics endpoint. By default all metrics are included.",
    convert_to=ArrayOfStrings,
    default=DEFAULT_KUBERNETES_API_CADVISOR_METRIC_NAME_INCLUDE_LIST,
)

define_config_option(
    __monitor__,
    "kubernetes_api_cadvisor_metric_name_exclude_list",
    "Optional metric name exclude list for Kubernetes cAdvisor API metrics endpoint. By default all metrics are included and no metrics are excluded.",
    convert_to=ArrayOfStrings,
    default=DEFAULT_KUBERNETES_API_CADVISOR_METRIC_NAME_EXCLUDE_LIST,
)

define_config_option(
    __monitor__,
    "kubernetes_api_cadvisor_metric_component_value_include_list",
    "Optional include list filter for metric component values.",
    convert_to=JsonObject,
    default=JsonObject({}),
)

# NOTE: This will result in substantial amount of bytes being written per line basis (uncompressed)
define_config_option(
    __monitor__,
    "include_node_name",
    "Set to true to include Kubernetes node name as an additional attribute with each metric log line.",
    convert_to=bool,
    default=False,
)
define_config_option(
    __monitor__,
    "include_cluster_name",
    "Set to true to include Kubernetes cluster name as an additional attribute with each metric log line.",
    convert_to=bool,
    default=False,
)

define_config_option(
    __monitor__,
    "logger_include_node_name",
    "True to include node name in the logger name. Setting this to False can come handy in debugging scenarios where we want to enable debug level for all the monitors without needing to know the node name.",
    convert_to=bool,
    default=True,
)

KUBERNETES_API_METRICS_URL = Template(
    "${k8s_api_url}/api/v1/nodes/${node_name}/proxy/metrics"
)
KUBERNETES_API_CADVISORS_METRICS_URL = Template(
    "${k8s_api_url}/api/v1/nodes/${node_name}/proxy/metrics/cadvisor"
)

OPEN_METRICS_MONITOR_MODULE = "scalyr_agent.builtin_monitors.openmetrics_monitor"
KUBERNETES_OPEN_METRICS_MONITOR_MODULE = (
    "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor"
)

# Annotation related constants
PROMETHEUS_ANNOTATION_SCRAPE_PORT = "prometheus.io/port"
PROMETHEUS_ANNOTATION_SCRAPE_SCHEME = "prometheus.io/scheme"
PROMETHEUS_ANNOTATION_SCRAPE_PATH = "prometheus.io/path"
SCALYR_AGENT_ANNOTATION_SCRAPE_ENABLE = "k8s.monitor.config.scalyr.com/scrape"

SCALYR_AGENT_ANNOTATION_SCRAPE_INTERVAL = (
    "k8s.monitor.config.scalyr.com/scrape_interval"
)
SCALYR_AGENT_ANNOTATION_SCRAPE_TIMEOUT = "k8s.monitor.config.scalyr.com/scrape_timeout"
# Set to False to disable ssl cert and hostname verification for a specific exporter (only applies
# if that exporter is using https scheme)
SCALYR_AGENT_ANNOTATION_SCRAPE_VERIFY_HTTPS = (
    "k8s.monitor.config.scalyr.com/verify_https"
)
SCALYR_AGENT_ANNOTATION_ATTRIBUTES = "k8s.monitor.config.scalyr.com/attributes"
SCALYR_AGENT_ANNOTATION_SCRAPE_METRICS_NAME_INCLUDE_LIST = (
    "k8s.monitor.config.scalyr.com/metric_name_include_list"
)
SCALYR_AGENT_ANNOTATION_SCRAPE_METRICS_NAME_EXCLUDE_LIST = (
    "k8s.monitor.config.scalyr.com/metric_name_exclude_list"
)
# A list of metric names for which rates should be calculated on the agent
SCALYR_AGENT_ANNOTATION_CALCULATE_RATE_METRIC_NAMES = (
    "k8s.monitor.config.scalyr.com/calculate_rate_metric_names"
)


# A regex to determine whether a string contains template directives
TEMPLATE_RE = re.compile(r"\${[^}]+}")


@dataclass
class K8sPod(object):
    uid: str
    name: str
    namespace: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    status_phase: str
    ips: List[str]


@dataclass
class OpenMetricsMonitorConfig(object):
    scrape_url: str
    scrape_interval: int
    scrape_timeout: int
    verify_https: bool
    attributes: Dict[str, str]
    metric_name_include_list: List[str]
    metric_name_exclude_list: List[str]
    calculate_rate_metric_names: List[str]


class TemplateWithSpecialCharacters(Template):
    """
    Custom template class which also supports ".", "/" and "-" characters. This way regular Kubernetes
    annotation keys such as, for example "app.kubernetes.io/instance", don't need to be transformed
    or sanitized.

    NOTE: This class only supports Python 3 (Open Metrics monitor rely on and use Python 3 only code
    since they are only used on Kubernetes with Docker Image which utilizes Python 3).
    """

    # Based on https://github.com/python/cpython/blob/main/Lib/string.py#L74

    delimiter = "$"
    pattern = r"""
    \$(?:
      (?P<escaped>\$)                        |   # Escape sequence of two delimiters
      (?P<named>[_a-z][_a-z0-9\-\.\/]*)      |   # delimiter and a Python identifier
      {(?P<braced>[_a-z][_a-z0-9\-\.\/]*)}   |   # delimiter and a braced identifier
      (?P<invalid>)                              # Other ill-formed delimiter exprs
    )
    """


class KubernetesOpenMetricsMonitor(ScalyrMonitor):
    def _initialize(self):
        self.__logger_include_node_name = self._config.get(
            "logger_include_node_name", True
        )

        # There can only be a single instance of this monitor running so we assign a custom id
        # with node name in it to make searching for this monitor logs easier
        module_name = self._config.get("module")
        if self.__logger_include_node_name:
            self._logger = scalyr_logging.getLogger(
                "%s(%s)" % (module_name, self.__get_node_name())
            )

        self.__scrape_interval = self._config.get(
            "scrape_interval", DEFAULT_SCRAPE_INTERVAL
        )
        self.__scrape_timeout = self._config.get(
            "scrape_timeout", DEFAULT_SCRAPE_TIMEOUT
        )
        self.__verify_https = self._config.get("verify_https", DEFAULT_VERIFY_HTTPS)

        self.__k8s_kubelet_host_ip = self._config.get("k8s_kubelet_host_ip")
        self.__k8s_kubelet_api_url_template = self._config.get(
            "k8s_kubelet_api_url_template"
        )

        self.__scrape_kubernetes_api_metrics = self._config.get(
            "scrape_kubernetes_api_metrics", False
        )
        self.__scrape_kubernetes_api_cadvisor_metrics = self._config.get(
            "scrape_kubernetes_api_cadvisor_metrics", False
        )

        self.__kubernetes_api_metrics_scrape_interval = self._config.get(
            "kubernetes_api_metrics_scrape_interval",
            DEFAULT_KUBERNETES_API_METRICS_SCRAPE_INTERVAL,
        )
        self.__kubernetes_api_cadvisor_metrics_scrape_interval = self._config.get(
            "kubernetes_api_cadvisor_metrics_scrape_interval",
            DEFAULT_KUBERNETES_API_CADVISOR_METRICS_SCRAPE_INTERVAL,
        )
        self.__include_node_name = self._config.get("include_node_name", False)
        self.__include_cluster_name = self._config.get("include_cluster_name", False)

        self.__k8s_api_url = self._global_config.k8s_api_url

        # Stores a list of monitor uids for static running monitors (Kubernetes API metrics and
        # Kubernetes API cAdvisor metrics)
        self.__static_running_monitors: List[str] = []

        # Maps scrape url to the monitor uid for all the monitors which have been dynamically
        # scheduled and started by us
        self.__running_monitors: Dict[str, str] = {}

        # Maps monitor uid to log config dictionary which is used by log watcher
        self.__watcher_log_configs: Dict[str, dict] = {}

        # Those variables get set when MonitorsManager is starting a monitor
        self.__log_watcher = None
        self.__module = None

        # Holds reference to the KubernetesApi and KubeletApi client which is populated lazily on
        # first access
        self._k8s = None
        self._kubelet = None

        self.__static_monitors_started = False

        self.__previous_running_monitors_count = 0

    @property
    def k8s(self):
        if not self._k8s:
            self._k8s = KubernetesApi.create_instance(
                self._global_config, k8s_api_url=self._global_config.k8s_api_url
            )

        return self._k8s

    @property
    def kubelet(self):
        # NOTE: "_initialize()" gets called on each config re-read to determine if there are any
        # changes and we need to restart the MonitorsManager so we need to perform any instantiation
        # with side effects outside "_initialize()".
        if not self._kubelet:
            self._kubelet = KubeletApi(
                k8s=self.k8s,
                host_ip=self.__k8s_kubelet_host_ip,
                node_name=self.__get_node_name(),
                kubelet_url_template=Template(self.__k8s_kubelet_api_url_template),
                verify_https=self._global_config.k8s_verify_kubelet_queries,
                ca_file=self._global_config.k8s_kubelet_ca_cert,
            )

        return self._kubelet

    def set_log_watcher(self, log_watcher):
        self.__log_watcher = log_watcher

    def config_from_monitors(self, manager):
        # Only a single instance of this monitor can run at a time
        monitors = manager.find_monitors(KUBERNETES_OPEN_METRICS_MONITOR_MODULE)

        if len(monitors) > 1:
            raise BadMonitorConfiguration(
                'Found an existing instance of "kubernetes_openmetrics_monitor". Only a'
                "single instance of this monitor can run at the same time.",
                "multiple_monitor_instances",
            )

    def gather_sample(self):
        if not self.__static_monitors_started:
            # On first iteration we schedule static global monitors which are not dynamically
            # updated. We intentionally do that here and don't override start() method to avoid
            # long blocking in the start() method.
            self.__schedule_static_open_metrics_monitors()
            self.__static_monitors_started = True

        self.__schedule_dynamic_open_metrics_monitors()
        self.__log_running_stats()

    def __log_running_stats(self):
        # We log a message either if the value from the previous run changes or every X minutes
        if self.__previous_running_monitors_count != len(self.__running_monitors):
            limit_once_per_x_secs = None
            limit_key = None
        else:
            limit_once_per_x_secs = 10 * 60
            limit_key = "k8s-om-mon-info"

        self._logger.info(
            f"There are currently {len(self.__running_monitors)} dynamic and {len(self.__static_running_monitors)} static open metrics monitors running",
            limit_once_per_x_secs=limit_once_per_x_secs,
            limit_key=limit_key,
        )

        self.__previous_running_monitors_count = len(self.__running_monitors)

    def __get_node_name(self):
        """
        Gets the node name of the node running the agent from downward API.
        """
        node_name = compat.os_environ_unicode.get("SCALYR_K8S_NODE_NAME", None)

        if not node_name:
            self._logger.warn(
                "SCALYR_K8S_NODE_NAME environment variable is not set, monitor will "
                "not work correctly."
            )

        return node_name

    def __get_cluster_name(self):
        """
        Gets name of the cluster this agent i srunning on.
        """
        # TODO: Similar to the old monitor, we could fall back to querying Kubelet in case this
        # environment variable is not available (but it should really be available since it's
        # documented in the docs and example config as required).
        cluster_name = compat.os_environ_unicode.get("SCALYR_K8S_CLUSTER_NAME")

        if not cluster_name:
            self._logger.warn(
                "SCALYR_K8S_CLUSTER_NAME environment variable is not set, monitor will "
                "not work correctly."
            )

        return cluster_name

    def __get_monitor_config_and_log_config(
        self,
        monitor_id: str,
        url: str,
        sample_interval: int,
        log_filename: str,
        scrape_timeout: int = None,
        verify_https: str = None,
        attributes: Dict[str, str] = None,
        ca_file: str = None,
        headers: dict = None,
        metric_name_include_list: List[str] = None,
        metric_name_exclude_list: List[str] = None,
        metric_component_value_include_list: dict = None,
        calculate_rate_metric_names: List[str] = None,
        include_node_name: bool = False,
        include_cluster_name: bool = False,
    ) -> Tuple[dict, dict]:
        """
        Return monitor config dictionary and log config dictionary for the provided arguments.
        """
        attributes = attributes or {}

        if scrape_timeout is None:
            scrape_timeout = self.__scrape_timeout

        if verify_https is None:
            verify_https = self.__verify_https

        headers = headers or {}

        if metric_name_include_list is None:
            metric_name_include_list = ["*"]

        if metric_name_exclude_list is None:
            metric_name_exclude_list = []

        if metric_component_value_include_list is None:
            metric_component_value_include_list = {}

        if calculate_rate_metric_names is None:
            calculate_rate_metric_names = []

        monitor_config = {
            "module": OPEN_METRICS_MONITOR_MODULE,
            "id": monitor_id,
            "url": url,
            "verify_https": verify_https,
            "ca_file": ca_file,
            "headers": JsonObject(headers or {}),
            # This gets changed dynamically per monitor via log config path
            "log_path": "scalyr_agent.builtin_monitors.openmetrics_monitor.log",
            "sample_interval": sample_interval,
            "timeout": scrape_timeout,
            "metric_name_include_list": metric_name_include_list,
            "metric_name_exclude_list": metric_name_exclude_list,
            "metric_component_value_include_list": JsonObject(
                metric_component_value_include_list
            ),
            "calculate_rate_metric_names": calculate_rate_metric_names,
        }

        extra_fields = {}
        extra_fields.update(attributes)

        # NOTE: k8s-node and k8s-cluster are special attributes so they always need to override
        # any custom attributes specified by the end user using "attributes" annotation
        if include_node_name:
            extra_fields["k8s-node"] = self.__get_node_name()

        if include_cluster_name:
            extra_fields["k8s-cluster"] = self.__get_cluster_name()

        if extra_fields:
            monitor_config["extra_fields"] = JsonObject(extra_fields)

        # NOTE: This monitor is only supported on Linux platform
        log_path = os.path.join(self._global_config.agent_log_path, log_filename)

        log_config = {
            "path": log_path,
        }

        return monitor_config, log_config

    def __schedule_static_open_metrics_monitors(self):
        """
        Schedule OpenMetrics monitors for global Kubernetes API metrics and Kubernetes API cAdvisor
        metrics endpoints.

        Those endpoints are not auto-discovered and are static per node which means we only set up those
        monitors once since they don't change.
        """
        self._logger.debug("Scheduling static open metrics monitors...")

        node_name = self.__get_node_name()

        template_context = {
            "k8s_api_url": self.__k8s_api_url,
            "node_name": node_name,
        }
        kubernetes_api_metrics_scrape_url = KUBERNETES_API_METRICS_URL.safe_substitute(
            template_context
        )
        kubernetes_api_cadvisor_metrics_scrape_url = (
            KUBERNETES_API_CADVISORS_METRICS_URL.safe_substitute(template_context)
        )

        monitors_manager = get_monitors_manager()

        ca_file = self._global_config.k8s_kubelet_ca_cert
        verify_https = self._global_config.k8s_verify_kubelet_queries
        headers = {
            "Authorization": "Bearer %s" % self.k8s.token,
        }

        # 1. Kubernetes API metrics monitor
        if self.__scrape_kubernetes_api_metrics:
            monitor_config, log_config = self.__get_monitor_config_and_log_config(
                monitor_id=f"{node_name}_kubernetes-api-metrics",
                url=kubernetes_api_metrics_scrape_url,
                verify_https=verify_https,
                ca_file=ca_file,
                headers=headers,
                sample_interval=self.__kubernetes_api_metrics_scrape_interval,
                log_filename=f"openmetrics_monitor-{node_name}-kubernetes-api-metrics.log",
                metric_name_include_list=self._config.get(
                    "kubernetes_api_metric_name_include_list"
                ),
                metric_name_exclude_list=self._config.get(
                    "kubernetes_api_metric_name_exclude_list"
                ),
                metric_component_value_include_list=self._config.get(
                    "kubernetes_api_metric_component_value_include_list"
                ),
                include_node_name=self.__include_node_name,
                include_cluster_name=self.__include_cluster_name,
            )

            monitor = monitors_manager.add_monitor(
                monitor_config=monitor_config,
                global_config=self._global_config,
                log_config=log_config,
            )

            response = monitor.check_connectivity()
            if response.status_code != 200:
                self._logger.warn(
                    f"Kubernetes API metrics endpoint {kubernetes_api_metrics_scrape_url} URL returned non-200 status code {response.status_code}, won't enable this monitor."
                )
                monitors_manager.remove_monitor(monitor.uid)
            else:
                self.__static_running_monitors.append(monitor.uid)
                self.__add_watcher_log_config(
                    monitor=monitor,
                    log_config=log_config,
                    scrape_url=kubernetes_api_metrics_scrape_url,
                )

        # 2. Kubernetes API cAdvisor metrics monitor
        if self.__scrape_kubernetes_api_cadvisor_metrics:
            monitor_config, log_config = self.__get_monitor_config_and_log_config(
                monitor_id=f"{node_name}_kubernetes-api-cadvisor-metrics",
                url=kubernetes_api_cadvisor_metrics_scrape_url,
                verify_https=verify_https,
                ca_file=ca_file,
                headers=headers,
                sample_interval=self.__kubernetes_api_cadvisor_metrics_scrape_interval,
                log_filename=f"openmetrics_monitor-{node_name}-kubernetes-api-cadvisor-metrics.log",
                metric_name_include_list=self._config.get(
                    "kubernetes_api_cadvisor_metric_name_include_list"
                ),
                metric_name_exclude_list=self._config.get(
                    "kubernetes_api_cadvisor_metric_name_exclude_list"
                ),
                metric_component_value_include_list=self._config.get(
                    "kubernetes_api_cadvisor_metric_component_value_include_list"
                ),
                include_node_name=self.__include_node_name,
                include_cluster_name=self.__include_cluster_name,
            )

            monitor = monitors_manager.add_monitor(
                monitor_config=monitor_config,
                global_config=self._global_config,
                log_config=log_config,
            )

            response = monitor.check_connectivity()
            if response.status_code != 200:
                self._logger.warn(
                    f"Kubernetes API cAdvisor metrics endpoint {kubernetes_api_cadvisor_metrics_scrape_url} URL returned non-200 status code {response.status_code}, won't enable this monitor."
                )
                monitors_manager.remove_monitor(monitor.uid)
            else:
                self.__static_running_monitors.append(monitor.uid)
                self.__add_watcher_log_config(
                    monitor=monitor,
                    log_config=log_config,
                    scrape_url=kubernetes_api_cadvisor_metrics_scrape_url,
                )

    def __schedule_dynamic_open_metrics_monitors(self):
        """
        Discover a list of metrics exporter URLs to scrape and configure, schedule and run
        corresponding ScalyrMonitor each scrape url.
        """
        start_ts = time.time()

        # 1. Query Kubelet API for pods running on this node and find exporters we want to scrape
        # (based on the annotations)
        k8s_pods = self.__get_k8s_pods()
        node_name = self.__get_node_name()

        self._logger.info(
            f"Found {len(k8s_pods)} pods on node {node_name}",
            limit_once_per_x_secs=10 * 60,
            limit_key="k8s-om-mon-sched-1",
        )

        # Maps scrape URL to the corresponding monitor config and K8sPod
        scrape_configs: Dict[str, Tuple[OpenMetricsMonitorConfig, K8sPod]] = {}

        # Dynamically query for scrape URLs based on the pods running on thise node and
        # corresponding pod annotations
        for pod in k8s_pods:
            scrape_config = self.__get_monitor_config_for_pod(pod=pod)

            if scrape_config:
                self._logger.debug(
                    f'Found scrape url "{scrape_config.scrape_url}" for pod {pod.namespace}/{pod.name} ({pod.uid}) with scrape config "{scrape_config}"',
                )
                assert (
                    scrape_config.scrape_url not in scrape_configs
                ), f"Found duplicated scrape url {scrape_config.scrape_url} for pod {pod.namespace}/{pod.name} ({pod.uid})"
                scrape_configs[scrape_config.scrape_url] = (scrape_config, pod)

        # TODO: Also re-schedule in case the config changes, not just the URL. In most cases, but
        # not all, config change will also result in URL change.
        # Schedule monitors as necessary (add any new ones and remove obsolete ones)
        current_scrape_urls = set(self.__running_monitors.keys())
        new_scrape_urls = set(scrape_configs.keys())

        unchanged_scrape_urls = current_scrape_urls.intersection(new_scrape_urls)
        to_add_scrape_urls = new_scrape_urls.difference(current_scrape_urls)
        to_remove_scrape_urls = current_scrape_urls.difference(new_scrape_urls)

        node_name = self.__get_node_name()

        if to_add_scrape_urls or to_remove_scrape_urls:
            self._logger.info(
                f"Found {len(new_scrape_urls)} URL(s) to scrape for node {node_name}, unchanged={unchanged_scrape_urls}, to add={to_add_scrape_urls}, to remove={to_remove_scrape_urls}"
            )
        else:
            # If nothing has changed, we use rate limit log to avoid spamming
            self._logger.info(
                f"Found {len(new_scrape_urls)} URL(s) to scrape for node {node_name}, unchanged={unchanged_scrape_urls}, to add={to_add_scrape_urls}, to remove={to_remove_scrape_urls}",
                limit_once_per_x_secs=10 * 60,
                limit_key="k8s-om-mon-sched-3",
            )

        for scrape_url in sorted(to_remove_scrape_urls):
            self.__remove_monitor(scrape_url=scrape_url)

        for scrape_url in sorted(to_add_scrape_urls):
            scrape_config, pod = scrape_configs[scrape_url]
            self.__add_monitor(scrape_config=scrape_config, pod=pod)

        end_ts = time.time()
        self._logger.info(
            f"Scheduling monitors took {(end_ts - start_ts):.3f} seconds.",
            limit_once_per_x_secs=10 * 60,
            limit_key="k8s-om-mon-sched-4",
        )

    def __add_monitor(
        self, scrape_config: OpenMetricsMonitorConfig, pod: K8sPod
    ) -> None:
        """
        Add and start monitor for the provided monitor config.
        """
        scrape_url = scrape_config.scrape_url
        if scrape_url in self.__running_monitors:
            self._logger.info(
                f"URL {scrape_url} is already being scrapped, skipping starting monitor"
            )
            return

        node_name = self.__get_node_name()
        monitor_config, log_config = self.__get_monitor_config_and_log_config(
            monitor_id=f"{node_name}_{pod.name}",
            url=scrape_url,
            sample_interval=scrape_config.scrape_interval or self.__scrape_interval,
            scrape_timeout=scrape_config.scrape_timeout,
            verify_https=scrape_config.verify_https,
            attributes=scrape_config.attributes,
            log_filename=f"openmetrics_monitor-{node_name}-{pod.name}.log",
            metric_name_include_list=scrape_config.metric_name_include_list,
            calculate_rate_metric_names=scrape_config.calculate_rate_metric_names,
            metric_name_exclude_list=scrape_config.metric_name_exclude_list,
            include_node_name=self.__include_node_name,
            include_cluster_name=self.__include_cluster_name,
        )

        monitors_manager = get_monitors_manager()
        monitor = monitors_manager.add_monitor(
            monitor_config=monitor_config,
            global_config=self._global_config,
            log_config=log_config,
        )

        self.__running_monitors[scrape_url] = monitor.uid

        self._logger.info(
            f'Started scrapping url "{scrape_url}" for pod {pod.namespace}/{pod.name} ({pod.uid})'
        )
        self._logger.debug(
            f'Using monitor config options for scrape url "{scrape_url}": {monitor_config}'
        )
        self._logger.debug(
            f'Using log config options for scrape url "{scrape_url}": {log_config}'
        )

        self.__add_watcher_log_config(
            monitor=monitor, log_config=log_config, scrape_url=scrape_url
        )

    def __remove_monitor(self, scrape_url: str) -> None:
        """
        Remove and stop monitor for the provided scrape url.
        """
        if scrape_url not in self.__running_monitors:
            return

        monitor_uid = self.__running_monitors[scrape_url]
        log_path = self.__watcher_log_configs[monitor_uid]["path"]

        monitors_manager = get_monitors_manager()
        monitors_manager.remove_monitor(monitor_uid)
        del self.__running_monitors[scrape_url]
        del self.__watcher_log_configs[monitor_uid]

        # Remove corresponding log watcher
        self.__log_watcher.schedule_log_path_for_removal(
            monitor_name="openmetrics_monitor",
            log_path=log_path,
        )

        # TODO: We should probably remove file from disk here since in case there is a lot of
        # exporter pod churn this could result in a lot of old unused files on disk. To do that,
        # we need to wait for the file to be fully flashed and ingested. Which means it's better
        # to handle that via periodic job which deletes files older than X days / similar.
        self._logger.info(f"Stopped scrapping url {scrape_url}")

    def __add_watcher_log_config(
        self, monitor: ScalyrMonitor, scrape_url: str, log_config: dict
    ) -> None:
        """
        Add watcher log config for the provided monitor.

        This ensures that the log file for that monitor is being ingested into Scalyr.
        """
        # Add config entry to the log watcher to make sure this file is being ingested
        watcher_log_config = {
            "parser": "agent-metrics",
            "path": log_config["path"],
        }
        self._logger.debug(
            f"Adding watcher log config {watcher_log_config} for monitor {monitor.uid} and scrape url {scrape_url}"
        )
        watcher_log_config = self.__log_watcher.add_log_config(
            monitor_name="openmetrics_monitor",
            log_config=watcher_log_config,
            force_add=True,
        )
        self.__watcher_log_configs[monitor.uid] = watcher_log_config

    def __get_k8s_pods(self) -> List[K8sPod]:
        """
        Query Kubelet API and retrieve a list of K8sPod objects.
        """
        response = self.kubelet.query_pods()
        pods = response.get("items", [])

        result = []
        for pod in pods:
            metadata = pod.get("metadata", {})
            uid = metadata.get("uid", "")
            name = metadata.get("name", "")
            namespace = metadata.get("namespace", "")
            labels = metadata.get("labels", {})
            annotations = metadata.get("annotations", {})
            status_phase = pod.get("status", {}).get("phase", "").lower()

            pod_ips = []
            for pod_ip_item in pod.get("status", {}).get("podIPs", []):
                if pod_ip_item.get("ip", None):
                    pod_ips.append(pod_ip_item["ip"])

            k8s_pod = K8sPod(
                uid=uid,
                name=name,
                namespace=namespace,
                labels=labels,
                annotations=annotations,
                ips=pod_ips,
                status_phase=status_phase,
            )
            result.append(k8s_pod)

        return result

    def __validate_dict_str_str(self, data: Dict[Any, Any]) -> bool:
        """
        Method which validates that all the key and values in teh dictionary are of a string type.
        """
        return all(isinstance(key, six.text_type) for key in data.keys()) and all(
            isinstance(value, six.text_type) for value in data.values()
        )

    def __get_attributes_template_context(self, pod: K8sPod) -> Dict[str, str]:
        """
        Return dictionary with a template context which can be used for variable substitution in
        "attributes" pod annotation values.

        For consistency we use the same approach as we use for Kubernetes log "attributes" annotation
        and rename_logfile.

        For example:

            ...
            k8s.monitor.config.scalyr.com/attributes: '{"app": "${pod_labels_app}"}'
            ..

        In this case, the value of the pod "app" label would be used.
        """
        context = {}

        # 1. Add labels
        labels = pod.labels or {}
        label_key = "pod_labels_"

        for label, value in labels.items():
            context[label_key + label] = value

        return context

    def __render_attributes_templates(
        self, pod: K8sPod, attributes: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Render any templates in the "attributes" annotation values.
        """
        template_context = self.__get_attributes_template_context(pod=pod)

        for key, value in attributes.items():
            if TEMPLATE_RE.search(value):
                attributes[key] = TemplateWithSpecialCharacters(value).safe_substitute(
                    template_context
                )

        return attributes

    def __get_monitor_config_for_pod(
        self, pod: K8sPod
    ) -> Optional[OpenMetricsMonitorConfig]:
        """
        Return OpenMetrics monitor config for the provided pod based on the annotations defined on
        the pod.

        If no matching annotations are found, None is returned.
        """
        if (
            pod.annotations.get(SCALYR_AGENT_ANNOTATION_SCRAPE_ENABLE, "false").lower()
            != "true"
        ):
            self._logger.debug(
                f"Discovered pod {pod.name} ({pod.uid}) doesn't have Open Metrics metrics scraping enabled, skipping it... (pod annotations={pod.annotations})"
            )

            return None

        self._logger.debug(
            f"Discovered pod {pod.name} ({pod.uid}) with Scalyr Open Metrics metric scraping enabled (pod annotations={pod.annotations})"
        )

        scrape_scheme = pod.annotations.get(
            PROMETHEUS_ANNOTATION_SCRAPE_SCHEME, DEFAULT_SCRAPE_SCHEME
        )
        scrape_port = pod.annotations.get(
            PROMETHEUS_ANNOTATION_SCRAPE_PORT, DEFAULT_SCRAPE_PORT
        )
        scrape_path = pod.annotations.get(
            PROMETHEUS_ANNOTATION_SCRAPE_PATH, DEFAULT_SCRAPE_PATH
        )

        node_ip = pod.ips[0] if pod.ips else None
        verify_https = (
            pod.annotations.get(
                SCALYR_AGENT_ANNOTATION_SCRAPE_VERIFY_HTTPS, str(self.__verify_https)
            ).lower()
            == "true"
        )

        attributes = pod.annotations.get(SCALYR_AGENT_ANNOTATION_ATTRIBUTES, {})
        self.__get_attributes_template_context(pod=pod)

        if attributes:
            # attributes annotation field needs to contain JSON string
            try:
                attributes = json_decode(attributes)
            except ValueError as e:
                self._logger.warn(
                    f'Failed to JSON decode "attributes" annotation for pod {pod.namespace}/{pod.name} ({pod.uid}). Attributes value "{attributes}". Error: {e}.'
                )
                attributes = {}

            # Validate value is an object / dictionary
            if not isinstance(attributes, dict):
                attributes_type = type(attributes)
                self._logger.warn(
                    f'Failed to JSON decode "attributes" annotation for pod {pod.namespace}/{pod.name} ({pod.uid}). Attributes value "{attributes}". Expected value to be an object/dictionary, got {attributes_type}.'
                )
                attributes = {}

            # Validate all the keys and values are of a string type
            valid_attributes_values = self.__validate_dict_str_str(data=attributes)

            if not valid_attributes_values:
                self._logger.warn(
                    f'Failed to validate "attributes" annotation for pod {pod.namespace}/{pod.name} ({pod.uid}). Attributes value "{attributes}". Expected all the keys and values to be a string.'
                )
                attributes = {}

            # At the end, perform any optional Template substitution
            attributes = self.__render_attributes_templates(
                pod=pod, attributes=attributes
            )

        if pod.status_phase != "running":
            self._logger.debug(
                f"Skipping pod {pod.namespace}/{pod.name} ({pod.uid}) which is not running status (status = {pod.status_phase})"
            )
            return None

        if scrape_scheme not in ["http", "https"]:
            self._logger.warn(
                f'Invalid scrape scheme "{scrape_scheme}" specified for pod {pod.namespace}/{pod.name} ({pod.uid})'
            )
            return None

        if not scrape_port:
            self._logger.warn(
                f'Pod {pod.namespace}/{pod.name} ({pod.uid}) is missing required "prometheus.io/port" annotation'
            )
            return None

        if not node_ip:
            self._logger.warn(
                f"Pod {pod.namespace}/{pod.name} ({pod.uid}) is missing podIps status attribute"
            )
            return None

        if len(pod.ips) > 1:
            self._logger.debug(
                "Pod {pod.namespace}/{pod.name} ({pod.uid}) has multiple IPs defined "
                "using the first one."
            )

        if scrape_path.startswith("/"):
            scrape_path = scrape_path[1:]

        scrape_url = f"{scrape_scheme}://{node_ip}:{scrape_port}/{scrape_path}"

        scrape_interval_string = pod.annotations.get(
            SCALYR_AGENT_ANNOTATION_SCRAPE_INTERVAL,
            self.__scrape_interval,
        )

        try:
            scrape_interval = int(scrape_interval_string)
        except ValueError:
            self._logger.warn(
                f"Pod {pod.namespace}/{pod.name} ({pod.uid}) contains invalid value for scrape interval ({scrape_interval_string}). Value must be a number."
            )
            return None

        scrape_timeout_string = pod.annotations.get(
            SCALYR_AGENT_ANNOTATION_SCRAPE_TIMEOUT,
            self.__scrape_timeout,
        )

        try:
            scrape_timeout = int(scrape_timeout_string)
        except ValueError:
            self._logger.warn(
                f"Pod {pod.namespace}/{pod.name} ({pod.uid}) contains invalid value for scrape timeout ({scrape_timeout_string}). Value must be a number."
            )
            return None

        metric_name_include_list = pod.annotations.get(
            SCALYR_AGENT_ANNOTATION_SCRAPE_METRICS_NAME_INCLUDE_LIST, None
        )
        metric_name_include_list = (
            metric_name_include_list and metric_name_include_list.split(",") or ["*"]
        )

        metric_name_exclude_list = pod.annotations.get(
            SCALYR_AGENT_ANNOTATION_SCRAPE_METRICS_NAME_EXCLUDE_LIST, None
        )
        metric_name_exclude_list = (
            metric_name_exclude_list and metric_name_exclude_list.split(",") or []
        )

        calculate_rate_metric_names = pod.annotations.get(
            SCALYR_AGENT_ANNOTATION_CALCULATE_RATE_METRIC_NAMES, None
        )
        calculate_rate_metric_names = (
            calculate_rate_metric_names and calculate_rate_metric_names.split(",") or []
        )

        # We prefix each metric name by the monitor name. This makes end user annotation based
        # configuration a bit nicer since the user doesn't need to specify the monitor name itself
        # there
        calculate_rate_metric_names = [
            "%s:%s" % ("openmetrics_monitor", metric_name)
            for metric_name in calculate_rate_metric_names
        ]

        return OpenMetricsMonitorConfig(
            scrape_url=scrape_url,
            scrape_interval=scrape_interval,
            scrape_timeout=scrape_timeout,
            verify_https=verify_https,
            attributes=attributes,
            metric_name_include_list=metric_name_include_list,
            metric_name_exclude_list=metric_name_exclude_list,
            calculate_rate_metric_names=calculate_rate_metric_names,
        )
