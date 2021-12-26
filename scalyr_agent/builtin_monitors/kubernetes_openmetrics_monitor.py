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

This monitor is designed to run on an agent which is deployed as a DeaamonSet on a Kubernetes
cluster. If you to scrape metrics in a OpenMetrics format from a static endpoint, you can use
"scalyr_agent.builtin_monitors.openmetrics_monitor" monitor.

It works by automatically discovering all the metrics exporter endpoints which are exposed on the
node the agent is running on.

It finds matching exporters by querying the Kubernetes API for pods which match special annotations.

If a pod contains the following annotations, it will be automatically discovered and scraped by this
monitor:

    * ``monitor.config.scalyr.com/scrape`` (required) - Set this value to "true" to enable metrics scraping
      for a specific pod.
    * ``prometheus.io/port`` (required) - Tells agent which port on the node to use when scraping metrics.
      Actual pod IP address is automatically discovered.
    * ``prometheus.io/protocol`` (optional, defaults to http) - Tells agent which protocol to use when
      building scrapper URL. Valid values are http and https.
    * ``prometheus.io/path`` (optional, defaults to /metrics) - Tells agent which request path to use when
      building scrapper URL.

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
            prometheus.io/scrape:             'true'
            prometheus.io/port:               '9100'
            monitor.config.scalyr.com/scrape: 'true'
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
        # NOTE: We don't need to use host network since we mount host stuff inside
        hostNetwork: true
        hostPID: true
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

## How it works

# Notes, Limitations

This monitor will only work correctly if the agent is deployed as a deamonset. That's because each
monitor instance will only discover metrics endpoints which are local to the node the agent is
running on.

## TODO

- [ ] Support for metric whitelist globs via annotations or similar
- [ ] Support for defining per exporter scrape interval via annotations
"""

from __future__ import absolute_import
from typing import Dict
from typing import List
from typing import Optional

import os
import time

from string import Template
from dataclasses import dataclass

import six

from scalyr_agent import ScalyrMonitor
from scalyr_agent import define_config_option
from scalyr_agent.monitors_manager import get_monitors_manager
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.monitor_utils.k8s import KubernetesApi
from scalyr_agent.monitor_utils.k8s import KubeletApi
from scalyr_agent import compat

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor``",
    convert_to=six.text_type,
    required_option=True,
)

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

define_config_option(
    __monitor__,
    "scrape_interval",
    "How often to scrape metrics from each of the dynamically discovered metric exporter endpoints. Defaults to 60 seconds.",
    convert_to=float,
    default=60.0,
)


@dataclass
class K8sPod(object):
    uid: str
    name: str
    namespace: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    status_phase: str
    ips: List[str]


class KubernetesOpenMetricsMonitor(ScalyrMonitor):
    def _initialize(self):
        # Maps scrape url to the monitor uid for all the monitors which have been dynamically
        # scheduled and started by us
        self.__running_monitors: Dict[str, str] = {}

        # Maps monitor uid to log config dictionary which is used by log watcher
        self.__watcher_log_configs: Dict[str, dict] = {}

        # Those variables get set when MonitorsManager is starting a monitor
        self.__log_watcher = None
        self.__module = None

        # Holds reference to the KubeletApi client which is populated lazily on first access
        self._kubelet = None

    @property
    def kubelet(self):
        # NOTE: "_initialize()" gets called on each config re-read to determine if there are any
        # changes and we need to restart the MonitorsManager so we need to perform any instantiation
        # with side effects outside "_initialize()".
        if not self._kubelet:
            k8s = KubernetesApi.create_instance(
                self._global_config, k8s_api_url=self._global_config.k8s_api_url
            )
            self._kubelet = KubeletApi(
                k8s=k8s,
                host_ip=self._config.get("k8s_kubelet_host_ip"),
                node_name=self.__get_node_name(),
                kubelet_url_template=Template(
                    self._config.get("k8s_kubelet_api_url_template")
                ),
                verify_https=self._global_config.k8s_verify_kubelet_queries,
                ca_file=self._global_config.k8s_kubelet_ca_cert,
            )

        return self._kubelet

    def set_log_watcher(self, log_watcher):
        self.__log_watcher = log_watcher

    def config_from_monitors(self, manager):
        # Only a single instance of this monitor can run at a time
        monitors = manager.find_monitors(
            "scalyr_agent.builtin_monitors.kubernetes_openmetrics_monitor"
        )

        if len(monitors) > 1:
            raise BadMonitorConfiguration(
                'Found an existing instance of "kubernetes_openmetrics_monitor". Only '
                "single instance of this monitor can run at the same time.",
                "multiple_monitor_instances",
            )

    def gather_sample(self):
        self._logger.info(
            f"There are currently {len(self.__running_monitors)} open metrics monitors running"
        )
        self.__schedule_open_metrics_monitors()

    def __get_node_name(self):
        """
        Gets the node name of the node running the agent from downward API
        """
        return compat.os_environ_unicode.get("SCALYR_K8S_NODE_NAME")

    def __schedule_open_metrics_monitors(self):
        """
        Discover a list of metrics exporter URLs to scrape and schedule corresponding monitor for
        each scrape url.
        """
        start_ts = int(time.time())

        # 1. Query Kubelet API for pods running on this node and find exporters we want to scrape
        # (based on the annotations)
        k8s_pods = self.__get_k8s_pods()
        node_name = self.__get_node_name()

        self._logger.info(f"Found {len(k8s_pods)} pods on node {node_name}")

        # Maps scrape URL to the corresponding pod
        scrape_configs: Dict[str, K8sPod] = {}

        # Dynamically query for scrape URLs based on the pods running on thise node and
        # corresponding pod annotations
        for pod in k8s_pods:
            scrape_url = self.__get_scrape_url_for_pod(pod=pod)

            if scrape_url:
                self._logger.info(
                    f'Found scrape url "{scrape_url}" for pod {pod.namespace}/{pod.name} ({pod.uid})'
                )
                assert (
                    scrape_url not in scrape_configs
                ), f"Found duplicated scrape url {scrape_url} for pod {pod.namespace}/{pod.name} ({pod.uid})"
                scrape_configs[scrape_url] = pod

        # Schedule monitors as necessary (add any new ones and remove obsolete ones)
        current_scrape_urls = set(self.__running_monitors.keys())
        new_scrape_urls = set(scrape_configs.keys())

        unchanged_scrape_urls = current_scrape_urls.intersection(new_scrape_urls)
        to_add_scrape_urls = new_scrape_urls.difference(current_scrape_urls)
        to_remove_scrape_urls = current_scrape_urls.difference(new_scrape_urls)

        node_name = self.__get_node_name()
        self._logger.info(
            f"Found {len(new_scrape_urls)} URL(s) to scrape for node {node_name}, unchanged={unchanged_scrape_urls}, to add={to_add_scrape_urls}, to remove={to_remove_scrape_urls}"
        )

        for scrape_url in to_remove_scrape_urls:
            self.__remove_monitor(scrape_url=scrape_url)

        for scrape_url in to_add_scrape_urls:
            self.__add_monitor(scrape_url=scrape_url, pod=scrape_configs[scrape_url])

        end_ts = int(time.time())
        self._logger.info(
            f"Scheduling monitors took {(end_ts - start_ts):.3f} seconds."
        )

    def __add_monitor(self, scrape_url: str, pod: K8sPod) -> None:
        """
        Add and start monitor for the provided scrape url.
        """
        if scrape_url in self.__running_monitors:
            self._logger.info(
                f"URL {scrape_url} is already being scrapped, skipping starting monitor"
            )
            return

        node_name = self.__get_node_name()
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.openmetrics_monitor",
            "id": f"{node_name}_{pod.name}",
            "url": scrape_url,
            "log_path": "scalyr_agent.builtin_monitors.openmetrics_monitor.log",
            "sample_interval": self._config.get("scrape_interval", 60.0),
        }
        log_filename = f"openmetrics_monitor-{node_name}-{pod.name}.log"
        # TODO: Use PlatformController specific method even though this monitor only supports Linux
        log_path = os.path.join(self._global_config.agent_log_path, log_filename)
        log_config = {
            "path": log_path,
        }
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

        # Add config entry to the log watcher to make sure this file is being ingested
        # TODO: Ensure checkpointing works correctly
        watcher_log_config = {
            "parser": "agent-metrics",
            "path": log_path,
        }
        self._logger.info(
            f"Adding log config {watcher_log_config} for monitor {monitor.uid} and scrape url {scrape_url}"
        )
        watcher_log_config = self.__log_watcher.add_log_config(
            "openmetrics_monitor", watcher_log_config, force_add=True
        )
        self.__watcher_log_configs[monitor.uid] = watcher_log_config

    def __remove_monitor(self, scrape_url: str) -> None:
        """
        Remove and stop monitor for the provided scrape url.
        """
        if scrape_url not in self.__running_monitors:
            return

        monitor_id = self.__running_monitors[scrape_url]
        log_path = self.__watcher_log_configs[monitor_id]["path"]

        monitors_manager = get_monitors_manager()
        monitors_manager.remove_monitor(monitor_id)
        del self.__running_monitors[scrape_url]
        del self.__watcher_log_configs[monitor_id]

        # Remove corresponding log watcher
        self.__log_watcher.schedule_log_path_for_removal(
            self.__module.module_name, log_path
        )

        # TODO: We should probably remove file from disk here since in case there is a lot of
        # exporter pod churn this could result in a lot of old unused files on disk. To do that,
        # we need to wait for the file to be fully flashed and ingested. Which means it's better
        # to handle that via periodic job which deletes files older than X days / similar.
        self._logger.info(f"Stopped scrapping url {scrape_url}")

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

    def __get_scrape_url_for_pod(self, pod: K8sPod) -> Optional[str]:
        """
        Return metric exporter scrape URL for the provided pod if the pod has scraping configured
        via annotations, otherwise return None.
        """
        if (
            pod.annotations.get("monitor.config.scalyr.com/scrape", "false").lower()
            != "true"
        ):
            return None

        self._logger.debug(
            f"Discovered pod {pod.name} ({pod.uid}) with Scalyr Open Metrics metric scraping enabled"
        )

        scrape_scheme = pod.annotations.get("prometheus.io/scheme", "http")
        scrape_port = pod.annotations.get("prometheus.io/port", None)
        scrape_path = pod.annotations.get("prometheus.io/path", "/metrics")
        node_ip = pod.ips[0] if pod.ips else None

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
        return scrape_url
