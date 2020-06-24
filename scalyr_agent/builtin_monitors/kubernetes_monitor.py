# Copyright 2018 Scalyr Inc.
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
# ------------------------------------------------------------------------
# author:  Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

import six


import datetime
import docker
import fnmatch
import glob
import traceback
import os
import random
import re
import stat
from string import Template
import threading
import time
from io import open
from six.moves.urllib.parse import quote_plus

from scalyr_agent import compat

from scalyr_agent import (
    ScalyrMonitor,
    define_config_option,
    define_metric,
    BadMonitorConfiguration,
)
import scalyr_agent.util as scalyr_util
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import (
    JsonObject,
    ArrayOfStrings,
    SpaceAndCommaSeparatedArrayOfStrings,
)
from scalyr_agent.monitor_utils.k8s import (
    KubernetesApi,
    KubeletApi,
    KubeletApiException,
    K8sApiTemporaryError,
    K8sConfigBuilder,
    K8sNamespaceFilter,
)
from scalyr_agent.monitor_utils.k8s import (
    K8sApiPermanentError,
    DockerMetricFetcher,
    QualifiedName,
)
import scalyr_agent.monitor_utils.k8s as k8s_utils
from scalyr_agent.third_party.requests.exceptions import ConnectionError

from scalyr_agent.util import StoppableThread, HistogramTracker


global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.kubernetes_monitor``",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "container_name",
    "Optional (defaults to None). Defines a regular expression that matches the name given to the "
    "container running the scalyr-agent.\n"
    "If this is None, the scalyr agent will look for a container running /usr/sbin/scalyr-agent-2 as the main process.\n",
    convert_to=six.text_type,
    default=None,
)

define_config_option(
    __monitor__,
    "container_check_interval",
    "Optional (defaults to 5). How often (in seconds) to check if containers have been started or stopped.",
    convert_to=int,
    default=5,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "api_socket",
    "Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket used to communicate with "
    "the docker API.   WARNING, if you have `mode` set to `syslog`, you must also set the "
    "`docker_api_socket` configuration option in the syslog monitor to this same value\n"
    "Note:  You need to map the host's /run/docker.sock to the same value as specified here, using the -v parameter, e.g.\n"
    "\tdocker run -v /run/docker.sock:/var/scalyr/docker.sock ...",
    convert_to=six.text_type,
    default="/var/scalyr/docker.sock",
)

define_config_option(
    __monitor__,
    "docker_api_version",
    "Optional (defaults to 'auto'). The version of the Docker API to use.  WARNING, if you have "
    "`mode` set to `syslog`, you must also set the `docker_api_version` configuration option in the "
    "syslog monitor to this same value\n",
    convert_to=six.text_type,
    default="auto",
)

define_config_option(
    __monitor__,
    "docker_log_prefix",
    "Optional (defaults to docker). Prefix added to the start of all docker logs.",
    convert_to=six.text_type,
    default="docker",
)

define_config_option(
    __monitor__,
    "docker_max_parallel_stats",
    "Optional (defaults to 20). Maximum stats requests to issue in parallel when retrieving container "
    "metrics using the Docker API.",
    convert_to=int,
    default=20,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "docker_percpu_metrics",
    "Optional (defaults to False). When `True`, emits cpu usage stats per core.  Note: This is disabled by "
    "default because it can result in an excessive amount of metric data on cpus with a large number of cores",
    convert_to=bool,
    default=False,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "max_previous_lines",
    "Optional (defaults to 5000). The maximum number of lines to read backwards from the end of the stdout/stderr logs\n"
    "when starting to log a containers stdout/stderr to find the last line that was sent to Scalyr.",
    convert_to=int,
    default=5000,
)

define_config_option(
    __monitor__,
    "readback_buffer_size",
    "Optional (defaults to 5k). The maximum number of bytes to read backwards from the end of any log files on disk\n"
    "when starting to log a containers stdout/stderr.  This is used to find the most recent timestamp logged to file "
    "was sent to Scalyr.",
    convert_to=int,
    default=5 * 1024,
)

define_config_option(
    __monitor__,
    "log_mode",
    'Optional (defaults to "docker_api"). Determine which method is used to gather logs from the '
    'local containers. If "docker_api", then this agent will use the docker API to contact the local '
    'containers and pull logs from them.  If "syslog", then this agent expects the other containers '
    'to push logs to this one using the syslog Docker log plugin.  Currently, "syslog" is the '
    "preferred method due to bugs/issues found with the docker API.  It is not the default to protect "
    "legacy behavior.\n",
    convert_to=six.text_type,
    default="docker_api",
)

define_config_option(
    __monitor__,
    "container_globs",
    "Optional (defaults to None). If true, a list of glob patterns for container names.  Only containers whose names "
    "match one of the glob patterns will be monitored.",
    convert_to=ArrayOfStrings,
    default=None,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "report_container_metrics",
    "Optional (defaults to True). If true, metrics will be collected from the container and reported  "
    "to Scalyr.  Note, metrics are only collected from those containers whose logs are being collected",
    convert_to=bool,
    default=True,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "report_k8s_metrics",
    "Optional (defaults to True). If true and report_container_metrics is true, metrics will be "
    "collected from the k8s and reported to Scalyr.",
    convert_to=bool,
    default=True,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_ignore_namespaces",
    'Optional (defaults to "kube-system"). A comma-delimited list of the namespaces whose pods\'s '
    "logs should not be collected and sent to Scalyr.",
    convert_to=SpaceAndCommaSeparatedArrayOfStrings,
    default=["kube-system"],
)

define_config_option(
    __monitor__,
    "k8s_ignore_pod_sandboxes",
    "Optional (defaults to True). If True then all containers with the label "
    "`io.kubernetes.docker.type` equal to `podsandbox` are excluded from the"
    "logs being collected",
    convert_to=bool,
    default=True,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_include_all_containers",
    "Optional (defaults to True). If True, all containers in all pods will be monitored by the kubernetes monitor "
    "unless they have an include: false or exclude: true annotation. "
    "If false, only pods/containers with an include:true or exclude:false annotation "
    "will be monitored. See documentation on annotations for further detail.",
    convert_to=bool,
    default=True,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_use_v2_attributes",
    "Optional (defaults to False). If True, will use v2 version of attribute names instead of "
    "the names used with the original release of this monitor.  This is a breaking change so could "
    "break searches / alerts if you rely on the old names",
    convert_to=bool,
    default=False,
)

define_config_option(
    __monitor__,
    "k8s_use_v1_and_v2_attributes",
    "Optional (defaults to False). If True, send attributes using both v1 and v2 versions of their"
    "names.  This may be used to fix breakages when you relied on the v1 attribute names",
    convert_to=bool,
    default=False,
)

define_config_option(
    __monitor__,
    "k8s_api_url",
    "DEPRECATED.",
    convert_to=six.text_type,
    default="https://kubernetes.default",
)

define_config_option(
    __monitor__,
    "k8s_cache_expiry_secs",
    "Optional (defaults to 30). The amount of time to wait between fully updating the k8s cache from the k8s api. "
    "Increase this value if you want less network traffic from querying the k8s api.  Decrease this value if you "
    "want dynamic updates to annotation configuration values to be processed more quickly.",
    convert_to=int,
    default=30,
)

define_config_option(
    __monitor__,
    "k8s_cache_purge_secs",
    "Optional (defaults to 300). The number of seconds to wait before purging unused items from the k8s cache",
    convert_to=int,
    default=300,
)

define_config_option(
    __monitor__,
    "k8s_cache_init_abort_delay",
    "Optional (defaults to 120). The number of seconds to wait for initialization of the kubernetes cache before aborting "
    "the kubernetes_monitor.",
    convert_to=int,
    default=120,
)

define_config_option(
    __monitor__,
    "k8s_parse_json",
    "Deprecated, please use `k8s_parse_format`. If set, and True, then this flag will override the `k8s_parse_format` to `auto`. "
    "If set and False, then this flag will override the `k8s_parse_format` to `raw`.",
    convert_to=bool,
    default=None,
)

define_config_option(
    __monitor__,
    "k8s_parse_format",
    "Optional (defaults to `auto`). Valid values are: `auto`, `json`, `cri` and `raw`. "
    "If `auto`, the monitor will try to detect the format of the raw log files, "
    "e.g. `json` or `cri`.  Log files will be parsed in this format before uploading to the server "
    "to extract log and timestamp fields.  If `raw`, the raw contents of the log will be uploaded to Scalyr. "
    "(Note: An incorrect setting can cause parsing to fail which will result in raw logs being uploaded to Scalyr, so please leave "
    "this as `auto` if in doubt.)",
    convert_to=six.text_type,
    default="auto",
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_always_use_cri",
    "Optional (defaults to False). If True, the kubernetes monitor will always try to read logs using the container runtime interface "
    "even when the runtime is detected as docker",
    convert_to=bool,
    default=False,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_always_use_docker",
    "Optional (defaults to False). If True, the kubernetes monitor will always try to get the list of running "
    "containers using docker even when the runtime is detected to be something different.",
    convert_to=bool,
    default=False,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_cri_query_filesystem",
    "Optional (defaults to False). If True, then when in CRI mode, the monitor will only query the filesystem for the list of active containers, rather than first querying the Kubelet API. This is a useful optimization when the Kubelet API is known to be disabled.",
    convert_to=bool,
    default=False,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "k8s_verify_api_queries",
    "Optional (defaults to True). If true, then the ssl connection for all queries to the k8s API will be verified using "
    "the ca.crt certificate found in the service account directory. If false, no verification will be performed. "
    "This is useful for older k8s clusters where certificate verification can fail.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "gather_k8s_pod_info",
    "Optional (defaults to False). If true, then every gather_sample interval, metrics will be collected "
    "from the docker and k8s APIs showing all discovered containers and pods. This is mostly a debugging aid "
    "and there are performance implications to always leaving this enabled",
    convert_to=bool,
    default=False,
    env_aware=True,
)

define_config_option(
    __monitor__,
    "include_daemonsets_as_deployments",
    "Deprecated",
    convert_to=bool,
    default=True,
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
    "k8s_sidecar_mode",
    "Optional, (defaults to False). If true, then logs will only be collected for containers "
    "running in the same Pod as the agent. This is used in situations requiring very high throughput.",
    env_aware=True,
    default=False,
)

# for now, always log timestamps to help prevent a race condition
# define_config_option( __monitor__, 'log_timestamps',
#                     'Optional (defaults to False). If true, stdout/stderr logs will contain docker timestamps at the beginning of the line\n',
#                     convert_to=bool, default=False)

define_metric(
    __monitor__,
    "docker.net.rx_bytes",
    "Total received bytes on the network interface",
    cumulative=True,
    unit="bytes",
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.rx_dropped",
    "Total receive packets dropped on the network interface",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.rx_errors",
    "Total receive errors on the network interface",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.rx_packets",
    "Total received packets on the network interface",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.tx_bytes",
    "Total transmitted bytes on the network interface",
    cumulative=True,
    unit="bytes",
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.tx_dropped",
    "Total transmitted packets dropped on the network interface",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.tx_errors",
    "Total transmission errors on the network interface",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "docker.net.tx_packets",
    "Total packets transmitted on the network intervace",
    cumulative=True,
    category="Network",
)

define_metric(
    __monitor__,
    "docker.mem.stat.active_anon",
    "The number of bytes of active memory backed by anonymous pages, excluding sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.active_file",
    "The number of bytes of active memory backed by files, excluding sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.cache",
    "The number of bytes used for the cache, excluding sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.hierarchical_memory_limit",
    "The memory limit in bytes for the container.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.inactive_anon",
    "The number of bytes of inactive memory in anonymous pages, excluding sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.inactive_file",
    "The number of bytes of inactive memory in file pages, excluding sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.mapped_file",
    "The number of bytes of mapped files, excluding sub-groups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.pgfault",
    "The total number of page faults, excluding sub-cgroups.",
    cumulative=True,
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.pgmajfault",
    "The number of major page faults, excluding sub-cgroups",
    cumulative=True,
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.pgpgin",
    "The number of charging events, excluding sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.pgpgout",
    "The number of uncharging events, excluding sub-groups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.rss",
    "The number of bytes of anonymous and swap cache memory (includes transparent hugepages), excluding sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.rss_huge",
    "The number of bytes of anonymous transparent hugepages, excluding sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.unevictable",
    "The number of bytes of memory that cannot be reclaimed (mlocked etc), excluding sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.writeback",
    "The number of bytes being written back to disk, excluding sub-cgroups",
    category="Memory",
)

define_metric(
    __monitor__,
    "docker.mem.stat.total_active_anon",
    "The number of bytes of active memory backed by anonymous pages, including sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_active_file",
    "The number of bytes of active memory backed by files, including sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_cache",
    "The number of bytes used for the cache, including sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_inactive_anon",
    "The number of bytes of inactive memory in anonymous pages, including sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_inactive_file",
    "The number of bytes of inactive memory in file pages, including sub-cgroups.",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_mapped_file",
    "The number of bytes of mapped files, including sub-groups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_pgfault",
    "The total number of page faults, including sub-cgroups.",
    cumulative=True,
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_pgmajfault",
    "The number of major page faults, including sub-cgroups",
    cumulative=True,
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_pgpgin",
    "The number of charging events, including sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_pgpgout",
    "The number of uncharging events, including sub-groups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_rss",
    "The number of bytes of anonymous and swap cache memory (includes transparent hugepages), including sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_rss_huge",
    "The number of bytes of anonymous transparent hugepages, including sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_unevictable",
    "The number of bytes of memory that cannot be reclaimed (mlocked etc), including sub-cgroups",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.stat.total_writeback",
    "The number of bytes being written back to disk, including sub-cgroups",
    category="Memory",
)


define_metric(
    __monitor__,
    "docker.mem.max_usage",
    "The max amount of memory used by container in bytes.",
    unit="bytes",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.usage",
    "The current number of bytes used for memory including cache.",
    unit="bytes",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.fail_cnt",
    "The number of times the container hit its memory limit",
    category="Memory",
)
define_metric(
    __monitor__,
    "docker.mem.limit",
    "The memory limit for the container in bytes.",
    unit="bytes",
    category="Memory",
)

define_metric(
    __monitor__,
    "docker.cpu.usage",
    "Total CPU consumed by container in nanoseconds",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.system_cpu_usage",
    "Total CPU consumed by container in kernel mode in nanoseconds",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.usage_in_usermode",
    "Total CPU consumed by tasks of the cgroup in user mode in nanoseconds",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.total_usage",
    "Total CPU consumed by tasks of the cgroup in nanoseconds",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.usage_in_kernelmode",
    "Total CPU consumed by tasks of the cgroup in kernel mode in nanoseconds",
    cumulative=True,
    category="CPU",
)

define_metric(
    __monitor__,
    "docker.cpu.throttling.periods",
    "The number of of periods with throttling active.",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.throttling.throttled_periods",
    "The number of periods where the container hit its throttling limit",
    cumulative=True,
    category="CPU",
)
define_metric(
    __monitor__,
    "docker.cpu.throttling.throttled_time",
    "The aggregate amount of time the container was throttled in nanoseconds",
    cumulative=True,
    category="CPU",
)

define_metric(
    __monitor__,
    "k8s.pod.network.rx_bytes",
    "The total received bytes on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.pod.network.rx_errors",
    "The total received errors on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.pod.network.tx_bytes",
    "The total transmitted bytes on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.pod.network.tx_errors",
    "The total transmission errors on a pod",
    cumulative=True,
    category="Network",
)

define_metric(
    __monitor__,
    "k8s.node.network.rx_bytes",
    "The total received bytes on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.node.network.rx_errors",
    "The total received errors on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.node.network.tx_bytes",
    "The total transmitted bytes on a pod",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "k8s.node.network.tx_errors",
    "The total transmission errors on a pod",
    cumulative=True,
    category="Network",
)

# A mapping of k8s controller kinds to the appropriate field name
# passed to the scalyr server for metrics that originate from pods
# controlled by that object. See #API-62
_CONTROLLER_KEYS = {
    "CronJob": "k8s-cron-job",
    "DaemonSet": "k8s-daemon-set",
    "Deployment": "k8s-deployment",
    "Job": "k8s-job",
    "ReplicaSet": "k8s-replica-set",
    "ReplicationController": "k8s-replication-controller",
    "StatefulSet": "k8s-stateful-set",
}

# A regex for splitting a container id and runtime
_CID_RE = re.compile("^(.+)://(.+)$")


class K8sInitException(Exception):
    """ Wrapper exception to indicate when the monitor failed to start due to
        a problem with initializing the k8s cache
    """


class WrappedStreamResponse(object):
    """ Wrapper for generator returned by docker.Client._stream_helper
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """

    def __init__(self, client, response, decode):
        self.client = client
        self.response = response
        self.decode = decode

    def __iter__(self):
        # pylint: disable=bad-super-call
        for item in super(DockerClient, self.client)._stream_helper(
            self.response, self.decode
        ):
            yield item


class WrappedRawResponse(object):
    """ Wrapper for generator returned by docker.Client._stream_raw_result
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """

    def __init__(self, client, response):
        self.client = client
        self.response = response

    def __iter__(self):
        # pylint: disable=bad-super-call
        for item in super(DockerClient, self.client)._stream_raw_result(self.response):
            yield item


class WrappedMultiplexedStreamResponse(object):
    """ Wrapper for generator returned by docker.Client._multiplexed_response_stream_helper
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """

    def __init__(self, client, response):
        self.client = client
        self.response = response

    def __iter__(self):
        for item in super(  # pylint: disable=bad-super-call
            DockerClient, self.client
        )._multiplexed_response_stream_helper(self.response):
            yield item


class DockerClient(docker.APIClient):  # pylint: disable=no-member
    """ Wrapper for docker.Client to return 'wrapped' versions of streamed responses
        so that we can have access to the response object, which allows us to get the
        socket in use, and shutdown the blocked socket from another thread (e.g. upon
        shutdown
    """

    def _stream_helper(self, response, decode=False):
        return WrappedStreamResponse(self, response, decode)

    def _stream_raw_result(self, response):
        return WrappedRawResponse(self, response)

    def _multiplexed_response_stream_helper(self, response):
        return WrappedMultiplexedStreamResponse(self, response)

    def _get_raw_response_socket(self, response):
        if response.raw._fp.fp:
            return super(DockerClient, self)._get_raw_response_socket(response)

        return None


def _split_datetime_from_line(line):
    """Docker timestamps are in RFC3339 format: 2015-08-03T09:12:43.143757463Z, with everything up to the first space
    being the timestamp.
    """
    log_line = line
    dt = datetime.datetime.utcnow()
    pos = line.find(" ")
    if pos > 0:
        dt = scalyr_util.rfc3339_to_datetime(line[0:pos])
        log_line = line[pos + 1 :]

    return (dt, log_line)


def _get_short_cid(container_id):
    """returns a shortened container id.  Useful for logging, where using a full length container id
       is not necessary and would just add noise to the log.
       The shortened container id will contain enough information to uniquely
       identify the container for most situations.  Note:  the returned value
       should never be used as a key in a dict for containers because there is
       always the remote possibility of a conflict (given a large enough number
       of containers).
    """
    # return the first 8 chars of the container id.
    # we don't need to check for length because even if len( container_id ) < 8
    # it's still valid to slice beyond the end of a string.  See:
    # https://docs.python.org/2/reference/expressions.html#slicings
    return container_id[:8]


def _ignore_old_dead_container(container, created_before=None):
    """
        Returns True or False to determine whether we should ignore the
        logs for a dead container, depending on whether the create time
        of the container is before a certain threshold time (specified in
        seconds since the epoch).

        If the container was created before the threshold time, then the
          container logs will be ignored.
        Otherwise the logs of the dead container will be uploaded.
    """

    # check for recently finished containers
    if created_before is not None:
        state = container.get("State", {})

        # ignore any that are finished and that are also too old
        if state != "running":
            created = container.get("Created", 0)  # default to a long time ago
            if created < created_before:
                return True

    return False


class ControlledCacheWarmer(StoppableThread):
    """A background thread that does a controlled warming of the pod cache.

    Tracks which pods are active and ensures that their information is cached in the pod cache.
    In order to warm the cache, a thread is run that requests each active pod's information one
    at a time.  It also tracks failures, moving active pods to a temporary blacklist if too many
    errors are seen.  While on the blacklist, a pod's information will not be fetched in order to
    populate the cache.
    """

    def __init__(
        self,
        name="warmer",
        max_failure_count=5,
        blacklist_time_secs=300,
        max_query_retries=3,
        logger=None,
    ):
        """Initializes the thread.

        @param name:  The name of this warmer, used when it logs its stats.
        @param max_failure_count: If this number of temporary failures is experienced when fetching a single
            pod's information, that pod will be placed on the blacklist.  Note, any permanent error will result
            in the pod being moved to the blacklist.
        @param blacklist_time_secs: The amount of time a pod will remain on the blacklist once it is moved there.
        @param max_query_retries:  The number of times we will retry a query to warm the pod when it fails due to
            a temporary error
        @param rate_limiter:  Rate limiter for api calls
        @param logger:  The logger to use when reporting results

        @type name: str
        @type max_failure_count: int
        @type blacklist_time_secs: double
        @type max_query_retries: int
        @type logger: Logger
        """
        StoppableThread.__init__(self, name="cache warmer and filter")
        self.__name = name
        self.__k8s_cache = None
        # Protects most fields, such as active_pods and containers_to_warm
        self.__lock = threading.Lock()
        self.__is_running = False
        # Used to notify threads of changes to the containers_to_warm state.
        self.__condition_var = threading.Condition(self.__lock)
        # Tracks the active pods.  Active pods are those docker or some other CRI has recently indicated is
        # running.  This variable maps container id to a WarmingEntry for the pod.
        self.__active_pods = dict()
        # The list of containers whose pods are eligible to be warmed in the cache.  Essentially, the active_pods
        # minus those already warmed or blacklisted.
        self.__containers_to_warm = []

        self.__max_failure_count = max_failure_count
        self.__blacklist_time_secs = blacklist_time_secs
        self.__max_query_retries = max_query_retries
        self.__logger = logger
        # The wallclock of when the last periodic report was written to the logger
        self.__last_report_time = None
        # Summarizes information about warming attempts.  There is an entry recording the running totals for
        # `total`, `success`, `already_warm`, `temp_error`, `perm_error`, `unknown_error`.
        self.__warming_attempts = dict()
        self.__last_reported_warming_attempts = dict()
        # Gathers statistics about how long it took to warm cache entries.  The values are expressed in seconds.
        self.__warming_times = HistogramTracker([1, 5, 30, 60, 120, 300, 600])

    def start(self):
        self.__lock.acquire()
        try:
            super(ControlledCacheWarmer, self).start()
            self.__is_running = True
        finally:
            self.__lock.release()

    def is_running(self):
        """
        @return True if `start` has been invoked on this instance
        @rtype: bool
        """
        self.__lock.acquire()
        try:
            return self.__is_running
        finally:
            self.__lock.release()

    def set_k8s_cache(self, k8s_cache):
        """Sets the cache to use.

        WARNING, this must be invoked before the thread is started.

        @param k8s_cache The cache instance to populate
        @type k8s_cache: KubernetesCache
        """
        self.__k8s_cache = k8s_cache

    def _prepare_to_stop(self):
        """Invoked when the stop has been requested to be stopped.
        """
        # Since our background thread may be waiting in `__pick_next_pod`, we poke the condition variable to
        # get it to wake up and notice the thread has stopped.
        self.__condition_var.acquire()
        try:
            self.__is_running = False
            self.__condition_var.notify_all()
        finally:
            self.__condition_var.release()

    def mark_has_been_used(self, container_id, unmark_to_warm=False):
        """
        Marks a WarmingEntry as having been used.  This typically means that
        the container id has been returned as a container that should be
        watched by the agent.
        @param container_id: the container id of the warming entry to mark as used
        @param unmark_to_warm: whether or not to unmark the WarmingEntry as something to warm
        """
        self.__lock.acquire()
        try:
            entry = self.__active_pods.get(container_id, None)
            if entry:
                entry.has_been_used = True

                if unmark_to_warm:
                    entry.is_recently_marked = False

        finally:
            self.__lock.release()

    def pending_first_use(self, container_id):
        """
        Returns whether a WarmingEntry for a container_id is awaiting its first use

        @param container_id: the container id to check

        @return: Whether or not the entry has been marked as used. If this is
        False, it typically means this container's log has not yet been
        included in the list of logs to copy. If this container is not part of
        the active set, always returns False.
        """
        self.__lock.acquire()
        try:
            entry = self.__active_pods.get(container_id, None)
            if entry:
                return not entry.has_been_used

        finally:
            self.__lock.release()

        # if we are here, then the container id didn't have a warming entry.
        return False

    def begin_marking(self):
        """Must be invoked before any container is marked as being active, by invoking `mark_to_warm`.
        This instructs this abstraction that the entire list of active containers is about to be marked.
        The list will end when `end_marking` is invoked.
        """
        self.__lock.acquire()
        try:
            for value in six.itervalues(self.__active_pods):
                value.is_recently_marked = False
        finally:
            self.__lock.release()

    def mark_to_warm(self, container_id, pod_namespace, pod_name):
        """Updates the state to reflect the specified container for the specified pod is active and
        its pod's information should be warmed in the cache if it has not already been.

        @param container_id:  The id of the container
        @param pod_namespace: The namespace for to the container's pod
        @param pod_name: The name of the container's pod.

        @type container_id: str
        @type pod_namespace: str
        @type pod_name: str
        """
        # This will be set to True if this entry was previously marked to be warmed but the cache indicated it
        # has already been warmed.
        self.__lock.acquire()
        try:
            if container_id not in self.__active_pods:
                self.__active_pods[container_id] = ControlledCacheWarmer.WarmingEntry(
                    pod_namespace, pod_name
                )
            self.__active_pods[container_id].is_recently_marked = True
        finally:
            self.__lock.release()

    def end_marking(self):
        """Indicates the end of marking all active containers has finished.

        Any container that was not marked since the last call to `begin_marking`, will no longer be considered active
        and therefore its pod's information will not be populated into the cache.
        """
        current_time = self._get_current_time()
        new_active_pods = dict()
        # Will hold a list of container ids whose pods are now in the cache, without us querying for them.
        already_warmed = None
        self.__lock.acquire()
        try:
            for key, value in six.iteritems(self.__active_pods):
                if value.is_recently_marked:
                    new_active_pods[key] = value
            self.__active_pods = new_active_pods
            # Take the opportunity to see if any of the container's pods are already warmed (in the cache)
            # as well as see any blacklisted containers should be moved back to active as well
            already_warmed = self.__update_is_warm()
            self.__update_blacklist(current_time)
            self.__update_containers_to_warm(current_time)
            self.__emit_report_if_necessary(current_time=current_time)
        except Exception:
            global_log.warn(
                "Unexpected exception in end_marking()\n%s\n" % traceback.format_exc(),
                limit_once_per_x_secs=300,
                limit_key="end-marking-exception",
            )
        finally:
            self.__lock.release()

            # We need to record the warming results while we don't hold the lock.
            if already_warmed is not None:
                for container_id in already_warmed:
                    self.__record_warming_result(container_id, already_warm=True)

    def is_warm(self, pod_namespace, pod_name, allow_expired=False):
        """Returns true if the specified pod's information is cached.

        @param pod_namespace: The namespace for the pod
        @param pod_name: The name for the pod
        @param allow_expired: If True, an object is considered present in cache even if it is expired.

        @type pod_namespace: str
        @type pod_name: str
        @type allow_expired: bool

        @rtype bool
        """
        return self.__k8s_cache.is_pod_cached(pod_namespace, pod_name, allow_expired)

    def get_report_stats(self):
        """
        Gathers stats of warming calls

        Used for testing

        @return: a dict of tuples containing current and previous warming attempt counts, keyed by result category
        @rtype: dict  (int, int)
        """
        self.__lock.acquire()
        try:
            return self.__gather_report_stats()
        finally:
            self.__lock.release()

    def __gather_report_stats(self):
        """
        Gathers stats of results of warming calls

        WARNING:  The caller must have already acquired _lock.

        @return: a dict of result counts keyed by result category
        """
        result = {}
        for category in [
            "total",
            "success",
            "already_warm",
            "temp_error",
            "perm_error",
            "unknown_error",
            "unhandled_error",
        ]:
            current_amount = self.__warming_attempts.get(category, 0)
            previous_amount = self.__last_reported_warming_attempts.get(category, 0)
            result[category] = (current_amount, previous_amount)
        return result

    def __emit_report_if_necessary(self, current_time=None):
        """Emit the periodic reporting lines if sufficient time has passed.

        WARNING:  The caller must have already acquired _lock.
        """
        if self.__logger is None:
            return

        if current_time is None:
            current_time = self._get_current_time()

        if (
            self.__last_report_time is None
            or current_time > self.__last_report_time + 300
        ):
            self.__last_report_time = current_time

            warm_attempts_info = ""
            stats = self.__gather_report_stats()
            for category, (current_amount, previous_amount) in six.iteritems(stats):
                warm_attempts_info += "%s=%d(delta=%d) " % (
                    category,
                    current_amount,
                    current_amount - previous_amount,
                )
            self.__logger.info(
                "controlled_cache_warmer[%s] pending_warming=%d blacklisted=%d %s warming_times=%s",
                self.__name,
                len(self.__containers_to_warm),
                self.__count_blacklisted(),
                warm_attempts_info,
                self.__warming_times.summarize(),
            )
            self.__last_reported_warming_attempts = self.__warming_attempts.copy()
            self.__warming_times.reset()

    def __count_blacklisted(self):
        """Counts and returns the total number of blacklisted containers.

        WARNING:  The caller must have already acquired _lock.

        :return:  The total number of blacklisted containers.
        :rtype: int
        """
        result = 0
        for value in six.itervalues(self.__active_pods):
            if value.blacklisted_until is not None:
                result += 1
        return result

    def __update_is_warm(self):
        """Updates the `is_warm` state information for the all pods in `__active_pods` based on the current
        contents of the cache.

        This method also calculates the list of all containers which are newly warmed (meaning the cache now indicates
        they are warm).

        If a container is newly cold (used to be warm but cache now says they are not), then we also reset the
        start warming time so that when we do go to start warming it, we measure it from the correct time.

        WARNING:  The caller must have already acquired _lock.

        @return: The list of container ids for all containers whose pods were previously not in the cache but now are.
        @rtype: [str]
        """
        already_warmed = []
        for key, entry in six.iteritems(self.__active_pods):
            was_warm = entry.is_warm
            # Check the actual cache.
            entry.is_warm = self.is_warm(entry.pod_namespace, entry.pod_name)
            # Reset the start of the warming time if we used to be warm and now need to warm (i.e., cache refresh).
            if was_warm and not entry.is_warm:
                entry.start_time = None

            if not was_warm and entry.is_warm:
                already_warmed.append(key)

        return already_warmed

    def __update_blacklist(self, current_time):
        """Updates the blacklist state information for the pods in `__active_pods`.

        Containers whose blacklisted time has expired are moved off of the blacklist.

        WARNING:  The caller must have already acquired _lock.

        @param current_time:  The current time in seconds past epoch.
        @type current_time: Number
        """
        for value in six.itervalues(self.__active_pods):
            if (
                value.blacklisted_until is not None
                and value.blacklisted_until < current_time
            ):
                # After coming off the blacklist, the pod gets a fresh start.  Reset all counters.
                # Note, we intentionally do not update `start_time` here because we want it to include blacklisting time.
                value.blacklisted_until = None
                value.blacklist_reason = None
                value.failure_count = 0

    def __update_containers_to_warm(self, current_time):
        """Updates the list of containers to warm based on the contents of the `__active_pods`.

        Containers are only considered for warming if their pod's information is not in the cache and
        if it is not on the blacklist.

        WARNING:  The caller must have already acquired _lock.

        @param current_time:  The current time in seconds past epoch.
        @type current_time: Number
        """
        # We see if the count changes.  If so, we need to notify listeners on __containers_to_warm.
        # The main listener is the background thread that waits to warm newly discovered containers.
        original_to_warm_count = len(self.__containers_to_warm)
        self.__containers_to_warm = []

        for key, value in six.iteritems(self.__active_pods):
            if not value.is_warm and value.blacklisted_until is None:
                self.__containers_to_warm.append(key)
                if value.start_time is None:
                    value.start_time = current_time

        if len(self.__containers_to_warm) != original_to_warm_count:
            self.__condition_var.notify_all()

    def block_until_idle(self, timeout=None):
        """Blocks the calling thread until the cache warming thread no longer has any containers that
        should be immediately warmed (either they are already warmed in the cache or they are on the blacklist
        so should not be warmed immediately).

        Takes an optional timeout as a parameter so that test code does not hang indefinitely

        WARNING:  Only used for tests.
        """
        start_time = time.time()
        self.__lock.acquire()
        try:
            while self._run_state.is_running() and len(self.__containers_to_warm) > 0:
                if timeout is not None and time.time() - start_time > timeout:
                    raise Exception("block_until_idle timed out")
                self.__condition_var.wait(timeout)
        finally:
            self.__lock.release()

    def warming_containers(self):
        """
        Returns a sorted list of the ids of the containers that will be warmed by this instance.

        WARNING: Only used for tests.

        @rtype: list
        """
        self.__lock.acquire()
        try:
            result = list(self.__containers_to_warm)
            result.sort()
            return result
        finally:
            self.__lock.release()

    def active_containers(self):
        """
        Returns a sorted list of the ids of the containers currently consider active by this instance.

        WARNING: Only used for tests.

        @rtype: list
        """
        self.__lock.acquire()
        try:
            result = list(self.__active_pods.keys())
            result.sort()
            return result
        finally:
            self.__lock.release()

    def blacklisted_containers(self):
        """
        Returns a sorted list of the ids of the containers currently blacklisted by this instance.

        WARNING: Only used for tests.

        @rtype: list
        """
        result = []
        self.__lock.acquire()
        try:
            for container_id, entry in six.iteritems(self.__active_pods):
                if entry.blacklisted_until is not None:
                    result.append(container_id)
            result.sort()
            return result
        finally:
            self.__lock.release()

    def __pick_next_pod(self):
        """Picks a random container's pod to warm.  Only containers that are active, are not warm in the
        cache, and are not blacklisted are considered.

        This method will block if there currently is no pod that needs to be warmed and wait until there is.

        :return: The container id, pod namespace and pod name of the pick container.  Or None, None, None if
            the warmer was stopped before a new container arrived.
        :rtype: (str, str, str)
        """
        self.__condition_var.acquire()
        try:
            while self._run_state.is_running() and len(self.__containers_to_warm) == 0:
                # We should be woken up by the notifies in _update_containers_to_warm
                self.__condition_var.wait()

            if len(self.__containers_to_warm) == 0:
                return None, None, None

            container_id = random.choice(self.__containers_to_warm)
            entry = self.__active_pods[container_id]
            return container_id, entry.pod_namespace, entry.pod_name

        finally:
            self.__condition_var.release()

    def __record_warming_result(
        self,
        container_id,
        success=None,
        already_warm=None,
        permanent_error=None,
        temporary_error=None,
        unknown_error=None,
        traceback_report=None,
    ):
        """Updates the state based on the result of warming the pod associated with the specified container.
        Only one of the result params (success, permanent_error, temporary_error, or unknown_error) should be
        specified.

        @param container_id: The id of the container associated with the pod
        @param success:  If True, the pod's information was successfully added to the cache.
        @param already_warm: If True, the pod's information was added to the cache between being marked to warm
            and when we were going to query the cache.
        @param permanent_error: The exception generated while warming the pod that indicated a permanent error.
            Permanent errors results in the pod being immediately blacklisted.
        @param temporary_error:  The exception generated while warming the pod that indicated a temporary error.
            Temporary errors results in the pod being blacklisted after __max_failure_count.
        @param unknown_error:  The exception generated while warming the pod that could not be categorized.
            It is treated as a temporary error.
        @param traceback_report:  The traceback of the exception if one of the error types

        @type container_id: str
        @type success: bool or None
        @type already_warm: bool or None
        @type permanent_error: Exception or None
        @type temporary_error: Exception or None
        @type unknown_error: Exception or None
        @type traceback_report: str or None
        """
        current_time = self._get_current_time()
        warm_time = None
        result_type = "not_set"
        exception_to_report = None
        self.__lock.acquire()
        try:
            if container_id in self.__active_pods:
                entry = self.__active_pods[container_id]
                if success:
                    warm_time = current_time - entry.start_time
                    entry.set_warm()
                    result_type = "success"
                elif already_warm:
                    entry.set_warm()
                    result_type = "already_warm"
                else:
                    if permanent_error:
                        result_type = "perm_error"
                        exception_to_report = permanent_error
                    elif temporary_error:
                        result_type = "temp_error"
                        exception_to_report = temporary_error
                    elif unknown_error:
                        result_type = "unknown_error"
                        exception_to_report = unknown_error
                    else:
                        result_type = "unhandled_error"

                    entry.failure_count += 1
                    if (
                        permanent_error
                        or entry.failure_count >= self.__max_failure_count
                    ):
                        entry.blacklisted_until = (
                            current_time + self.__blacklist_time_secs
                        )
                        entry.blacklist_reason = result_type
                self.__update_containers_to_warm(current_time)

        finally:
            self.__warming_attempts["total"] = (
                self.__warming_attempts.get("total", 0) + 1
            )
            self.__warming_attempts[result_type] = (
                self.__warming_attempts.get(result_type, 0) + 1
            )

            if warm_time is not None:
                self.__warming_times.add_sample(warm_time)

            self.__lock.release()
            if exception_to_report is not None and self.__logger is not None:
                self.__logger.error(
                    "An error of type %s was seen when warming container %s.  Exception was %s: %s",
                    result_type,
                    container_id,
                    six.text_type(exception_to_report),
                    six.text_type(traceback_report),
                    limit_once_per_x_secs=300,
                    limit_key="warmer-record-result-%s" % result_type,
                )

    @staticmethod
    def _get_current_time():
        """Returns the current time.

        This method exists so it can be overridden during testing.
        """
        return time.time()

    def run_and_propagate(self):
        """Runs the background thread that is responsible for actually warming the active pod's information.
        """
        assert self.__k8s_cache is not None

        consecutive_warm_pods = 0
        while self._run_state.is_running():
            try:
                container_id, pod_namespace, pod_name = self.__pick_next_pod()
                if container_id is not None and not self.is_warm(
                    pod_namespace, pod_name
                ):
                    consecutive_warm_pods = 0
                    try:
                        self.__k8s_cache.pod(
                            pod_namespace, pod_name, allow_expired=False
                        )
                        self.__record_warming_result(container_id, success=True)
                    except K8sApiPermanentError as e:
                        self.__record_warming_result(
                            container_id,
                            permanent_error=e,
                            traceback_report=traceback.format_exc(),
                        )
                    except K8sApiTemporaryError as e:
                        self.__record_warming_result(
                            container_id,
                            temporary_error=e,
                            traceback_report=traceback.format_exc(),
                        )
                    except Exception as e:
                        self.__record_warming_result(
                            container_id,
                            unknown_error=e,
                            traceback_report=traceback.format_exc(),
                        )
                else:
                    # Something else warmed the pod before we got a chance.  Just take the win.
                    self.__record_warming_result(container_id, already_warm=True)
                    consecutive_warm_pods += 1
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_3,
                        "CacheWarmer.run_and_propagate: %s consecutive warms in a row: %s %s %s"
                        % (
                            consecutive_warm_pods,
                            container_id,
                            pod_namespace,
                            pod_name,
                        ),
                    )
                    if consecutive_warm_pods == 10:
                        # TODO-163: Get rid of circuit breaker.
                        self._run_state.sleep_but_awaken_if_stopped(0.1)
            except Exception:
                global_log.exception("cacher warmer uncaught exception")

    class WarmingEntry(object):
        """Used to represent an active container whose pod information should be warmed in the cache.
        """

        def __init__(self, pod_namespace, pod_name):
            # The associated pod's namespace.
            self.pod_namespace = pod_namespace
            # The associated pod's name.
            self.pod_name = pod_name
            # Whether or not this is a new warming entry that has never been used
            self.has_been_used = False
            # The most recent time when this pod was requested to be warmed - gets updated after cache expiry
            self.start_time = None
            # Whether or not it is currently warmed.
            self.is_warm = False
            # Used to indicate if it is been marked in the most recent marking run started by `begin_marking`.
            self.is_recently_marked = False
            # The number of consecutive failures seen while trying to warm the pod's information.
            self.failure_count = 0
            # If not none, this container has been blacklisted.  It will not be warmed again until the wallclock
            # time stored in this variable has been reached.
            self.blacklisted_until = None
            # The reason for the blacklisting.
            self.blacklist_reason = None

        def __repr__(self):
            s = "WarmingEntry:"
            for key, val in self.__dict__.items():
                s += "\n\t%s: %s" % (key, val)
            return s + "\n"

        def set_warm(self):
            """
            Sets the entry to warm, and resets failure count and black list status.
            """
            self.is_warm = True
            self.failure_count = 0
            self.blacklisted_until = None
            self.blacklist_reason = None


def _get_containers(
    client,
    ignore_container=None,
    ignored_pod=None,
    restrict_to_container=None,
    logger=None,
    only_running_containers=True,
    running_or_created_after=None,
    glob_list=None,
    include_log_path=False,
    k8s_cache=None,
    k8s_include_by_default=True,
    k8s_namespaces_to_include=None,
    ignore_pod_sandboxes=True,
    current_time=None,
    controlled_warmer=None,
):
    """Queries the Docker API and returns a dict of running containers that maps container id to container name, and other info
        @param client: A docker.Client object
        @param ignore_container: String, a single container id to exclude from the results (useful for ignoring the scalyr_agent container)
        @param ignored_pod: QualifiedPod, a pod name and namespace to exclude from results (useful for ignoring the scalyr_agent container)
        @param restrict_to_container: String, a single continer id that will be the only returned result
        @param logger: scalyr_logging.Logger.  Allows the caller to write logging output to a specific logger.  If None the default agent.log
            logger is used.
        @param only_running_containers: Boolean.  If true, will only return currently running containers
        @param running_or_created_after: Unix timestamp.  If specified, the results will include any currently running containers *and* any
            dead containers that were created after the specified time.  Used to pick up short-lived containers.
        @param glob_list: List of strings.  A glob string limits results to containers whose container names match the glob
        @param include_log_path: Boolean.  If true include the path to the raw log file on disk as part of the extra info mapped to the container id.
        @param k8s_cache: KubernetesCache.  If not None, k8s information (if it exists) for the container will be added as part of the extra info mapped to the container id
        @param k8s_include_by_default: Boolean.  If True, then all k8s containers are included by default, unless an include/exclude annotation excludes them.
            If False, then all k8s containers are excluded by default, unless an include/exclude annotation includes them.
        @param k8s_namespaces_to_include: K8sNamespaceFilter  The filter for namespaces whose containers should be included.  If None, all will be included.
        @param ignore_pod_sandboxes: Boolean.  If True then any k8s pod sandbox containers are ignored from the list of monitored containers
        @param current_time: Timestamp since the epoch
        @param controlled_warmer:  If the pod cache should be proactively warmed using the controlled warmer
            strategy, then the warmer instance to use.
    """
    if logger is None:
        logger = global_log

    k8s_labels = {
        "pod_uid": "io.kubernetes.pod.uid",
        "pod_name": "io.kubernetes.pod.name",
        "pod_namespace": "io.kubernetes.pod.namespace",
        "k8s_container_name": "io.kubernetes.container.name",
    }

    if k8s_namespaces_to_include is None:
        k8s_namespaces_to_include = K8sNamespaceFilter.include_all()

    if running_or_created_after is not None:
        only_running_containers = False

    result = {}
    try:
        filters = (
            {"id": restrict_to_container} if restrict_to_container is not None else None
        )
        response = client.containers(filters=filters, all=not only_running_containers)
        try:
            if controlled_warmer is not None:
                controlled_warmer.begin_marking()

            for container in response:
                cid = container["Id"]
                short_cid = _get_short_cid(cid)

                if ignore_container is not None and cid == ignore_container:
                    continue

                # Note we need to *include* results that were created after the 'running_or_created_after' time.
                # that means we need to *ignore* any containers created before that
                # hence the reason 'create_before' is assigned to a value named '...created_after'
                is_old_dead_container = _ignore_old_dead_container(
                    container, created_before=running_or_created_after
                )

                # AGENT-373/270 - we don't want to ignore containers that are still
                # pending first use, otherwise we will miss out on short-lived logs
                pending_first_use = False
                if controlled_warmer is not None:
                    pending_first_use = controlled_warmer.pending_first_use(cid)

                # ignore containers that are old and dead and whose logs are already being copied
                if is_old_dead_container and not pending_first_use:
                    continue

                if len(container["Names"]) > 0:
                    name = container["Names"][0].lstrip("/")

                    # ignore any pod sandbox containers
                    if ignore_pod_sandboxes:
                        container_type = container.get("Labels", {}).get(
                            "io.kubernetes.docker.type", ""
                        )
                        if container_type == "podsandbox":
                            continue

                    add_container = True

                    if glob_list:
                        add_container = False
                        for glob_pattern in glob_list:
                            if fnmatch.fnmatch(name, glob_pattern):
                                add_container = True
                                break

                    if add_container:
                        log_path = None
                        k8s_info = None
                        status = None
                        if include_log_path or k8s_cache is not None:
                            try:
                                info = client.inspect_container(cid)

                                log_path = (
                                    info["LogPath"]
                                    if include_log_path and "LogPath" in info
                                    else None
                                )

                                if not only_running_containers:
                                    status = info["State"]["Status"]

                                if k8s_cache is not None:
                                    config = info.get("Config", {})
                                    labels = config.get("Labels", {})

                                    k8s_info = {}
                                    missing_field = False

                                    for key, label in six.iteritems(k8s_labels):
                                        value = labels.get(label)
                                        if value:
                                            k8s_info[key] = value
                                        else:
                                            missing_field = True
                                            logger.warn(
                                                "Missing kubernetes label '%s' in container %s"
                                                % (label, short_cid),
                                                limit_once_per_x_secs=300,
                                                limit_key="docker-inspect-k8s-%s"
                                                % short_cid,
                                            )

                                    if missing_field:
                                        logger.log(
                                            scalyr_logging.DEBUG_LEVEL_1,
                                            "Container Labels %s"
                                            % (scalyr_util.json_encode(labels)),
                                            limit_once_per_x_secs=300,
                                            limit_key="docker-inspect-container-dump-%s"
                                            % short_cid,
                                        )

                                    if (
                                        "pod_name" in k8s_info
                                        and "pod_namespace" in k8s_info
                                    ):
                                        # TODOOcz:
                                        if (
                                            k8s_info["pod_namespace"]
                                            not in k8s_namespaces_to_include
                                        ):
                                            logger.log(
                                                scalyr_logging.DEBUG_LEVEL_2,
                                                "Excluding container '%s' based on excluded namespaces: %s in %s"
                                                % (
                                                    short_cid,
                                                    k8s_info["pod_namespace"],
                                                    k8s_namespaces_to_include,
                                                ),
                                            )
                                            continue

                                        # If we are warming the cache using the controlled strategy, then skip this
                                        # container if it is not yet warmed in the pod.  That way, all code from here
                                        # on out is guaranteed to not issue an API request if the pod is
                                        # cached.
                                        namespace = k8s_info["pod_namespace"]
                                        pod_name = k8s_info["pod_name"]

                                        if controlled_warmer is not None:
                                            controlled_warmer.mark_to_warm(
                                                cid, namespace, pod_name
                                            )
                                            # Must not exclude this pod if it's expired but still present in cache.
                                            # Otherwise, the pod's logfile will be dropped and re-watched repeatedly
                                            # resulting in continuous thrashing.
                                            if not controlled_warmer.is_warm(
                                                namespace, pod_name, allow_expired=True
                                            ):
                                                logger.log(
                                                    scalyr_logging.DEBUG_LEVEL_2,
                                                    "Excluding container '%s' because not in cache warmer"
                                                    % short_cid,
                                                )
                                                continue

                                        if (
                                            ignored_pod is not None
                                            and k8s_info["pod_namespace"]
                                            == ignored_pod.namespace
                                            and k8s_info["pod_name"] == ignored_pod.name
                                        ):
                                            logger.log(
                                                scalyr_logging.DEBUG_LEVEL_2,
                                                "Excluding container '%s' for ignored_pod: %s/%s"
                                                % (
                                                    short_cid,
                                                    k8s_info["pod_namespace"],
                                                    k8s_info["pod_name"],
                                                ),
                                            )
                                            continue

                                        pod = k8s_cache.pod(
                                            namespace,
                                            pod_name,
                                            current_time,
                                            ignore_k8s_api_exception=True,
                                        )
                                        if pod:
                                            # We've read the pod from the cache, so any WarmingEntry associated
                                            # with this has now been used.  This ensures we pick up short lived
                                            # logs that finished before they had a warm entry in the k8s_cache
                                            if controlled_warmer is not None:
                                                controlled_warmer.mark_has_been_used(
                                                    cid,
                                                    unmark_to_warm=is_old_dead_container,
                                                )

                                            k8s_info["pod_info"] = pod

                                            k8s_container = k8s_info.get(
                                                "k8s_container_name", None
                                            )

                                            # check to see if we should exclude this container
                                            default_exclude = not k8s_include_by_default
                                            exclude = pod.exclude_pod(
                                                container_name=k8s_container,
                                                default=default_exclude,
                                            )

                                            if exclude:
                                                if pod.annotations:
                                                    logger.log(
                                                        scalyr_logging.DEBUG_LEVEL_2,
                                                        "Excluding container '%s' based on pod annotations, %s"
                                                        % (
                                                            short_cid,
                                                            six.text_type(
                                                                pod.annotations
                                                            ),
                                                        ),
                                                    )
                                                continue

                                            # add a debug message if containers are excluded by default but this container is included
                                            if default_exclude and not exclude:
                                                logger.log(
                                                    scalyr_logging.DEBUG_LEVEL_2,
                                                    "Including container '%s' based on pod annotations, %s"
                                                    % (
                                                        short_cid,
                                                        six.text_type(pod.annotations),
                                                    ),
                                                )

                            except Exception as e:
                                logger.error(
                                    "Error inspecting container '%s' - %s, %s"
                                    % (cid, e, traceback.format_exc()),
                                    limit_once_per_x_secs=300,
                                    limit_key="docker-api-inspect",
                                )

                        result[cid] = {"name": name, "log_path": log_path}

                        if status:
                            result[cid]["status"] = status

                        if k8s_info:
                            result[cid]["k8s_info"] = k8s_info

                else:
                    result[cid] = {"name": cid, "log_path": None}
        finally:
            if controlled_warmer is not None:
                controlled_warmer.end_marking()

    except Exception as e:  # container querying failed
        logger.exception(
            "Error querying running containers: %s, filters=%s, only_running_containers=%s"
            % (six.text_type(e), filters, only_running_containers),
            limit_once_per_x_secs=300,
            limit_key="k8s-docker-api-running-containers",
        )
        result = None

    return result


class ContainerEnumerator(object):
    """
    Base class that defines an api for enumerating all containers running on a node
    """

    def __init__(self, agent_pod, is_sidecar_mode=False):
        """
        @param ignored_pod: A pod whose containers should not be included in the returned list.  Typically, this
            is the agent pod.
        @type ignored_pod: QualifiedName
        """
        self._agent_pod = agent_pod
        self._is_sidecar_mode = is_sidecar_mode

        if self._is_sidecar_mode:
            self._ignored_pod = None
        else:
            self._ignored_pod = self._agent_pod

    def _get_containers(
        self,
        running_or_created_after=None,
        glob_list=None,
        k8s_cache=None,
        k8s_include_by_default=True,
        k8s_namespaces_to_include=None,
        current_time=None,
    ):
        raise NotImplementedError()

    def get_containers(
        self,
        running_or_created_after=None,
        glob_list=None,
        k8s_cache=None,
        k8s_include_by_default=True,
        k8s_namespaces_to_include=None,
        current_time=None,
    ):
        containers = self._get_containers(
            running_or_created_after=running_or_created_after,
            glob_list=glob_list,
            k8s_cache=k8s_cache,
            k8s_include_by_default=k8s_include_by_default,
            k8s_namespaces_to_include=k8s_namespaces_to_include,
            current_time=current_time,
        )

        # Short circuit the filtering logic if there is no pod filtering required.
        if not self._is_sidecar_mode:
            return containers

        # Short circuit the filtering logic if sidecar mode is enabled but there's no agent_pod,
        # As this means no logs will be sent.
        if self._agent_pod is None:
            global_log.warn(
                "Sidecar_mode enabled but no agent_pod was specified",
                limit_once_per_x_secs=300,
                limit_key="sidecar-agent-pod",
            )
            return {}

        # Filter containers to those that belong to the agent_pod, for use with using sidecar mode
        # This is done in the parent ContainerEnumerator class so it doesn't have to be duplicated in the
        # DockerEnumerator and CRIEnumerator
        filtered_containers = {}
        for cid, info in six.iteritems(containers):
            k8s_info = info.get("k8s_info", {})
            pod_name = k8s_info.get("pod_name", None)
            pod_namespace = k8s_info.get("pod_namespace", None)
            qualified_name = QualifiedName(pod_namespace, pod_name)

            if qualified_name.is_valid() and qualified_name == self._agent_pod:
                filtered_containers[cid] = info
        return filtered_containers


class DockerEnumerator(ContainerEnumerator):
    """
    Container Enumerator that retrieves the list of containers by querying the docker remote API over the docker socket by usin
    a docker.Client
    """

    def __init__(
        self, client, agent_pod, controlled_warmer=None, is_sidecar_mode=False
    ):
        """
        @param client: The docker client to use for accessing docker
        @param agent_pod: The QualfiedName of the agent pod.
        @param controlled_warmer:  If the pod cache should be proactively warmed using the controlled warmer
            strategy, then the warmer instance to use.
        @param restrict_to_pod: The pod name to restrict logs to
        @type client: DockerClient
        @type agent_pod: QualifiedName
        @type controlled_warmer: ControlledCacheWarmer or None
        @type restrict_to_pod: str
        """
        super(DockerEnumerator, self).__init__(
            agent_pod, is_sidecar_mode=is_sidecar_mode
        )
        self._client = client
        self.__controlled_warmer = controlled_warmer

    def _get_containers(
        self,
        running_or_created_after=None,
        glob_list=None,
        k8s_cache=None,
        k8s_include_by_default=True,
        k8s_namespaces_to_include=None,
        current_time=None,
    ):
        return _get_containers(
            self._client,
            ignored_pod=self._ignored_pod,
            running_or_created_after=running_or_created_after,
            glob_list=glob_list,
            include_log_path=True,
            k8s_cache=k8s_cache,
            k8s_include_by_default=k8s_include_by_default,
            k8s_namespaces_to_include=k8s_namespaces_to_include,
            current_time=current_time,
            controlled_warmer=self.__controlled_warmer,
        )


class CRIEnumerator(ContainerEnumerator):
    """
    Container Enumerator that retrieves the list of containers by querying the Kubelet API for a list of all pods on the node
    and then from the list of pods, retrieve all the relevant container information
    """

    def __init__(
        self,
        global_config,
        agent_pod,
        k8s_api_url,
        query_filesystem,
        node_name,
        kubelet_api_host_ip,
        kubelet_api_url_template,
        is_sidecar_mode=False,
    ):
        """
        @param global_config: Global configuration
        @param agent_pod: The QualfiedName of the agent pod.
        @param k8s_api_url: The URL to use for accessing the API
        @param query_filesystem: Whether or not to get the container list using the filesystem-based approach
        @param kubelet_api_host_ip: The HOST IP to use for accessing the Kubelet API
        @type agent_pod: QualifiedName
        @type k8s_api_url: str
        @type query_filesystem: bool
        @type kubelet_api_host_ip: str
        """
        super(CRIEnumerator, self).__init__(agent_pod, is_sidecar_mode=is_sidecar_mode)
        k8s = KubernetesApi.create_instance(global_config, k8s_api_url=k8s_api_url)
        self._kubelet = KubeletApi(
            k8s,
            host_ip=kubelet_api_host_ip,
            node_name=node_name,
            kubelet_url_template=Template(kubelet_api_url_template),
            verify_https=global_config.k8s_verify_kubelet_queries,
            ca_file=global_config.k8s_kubelet_ca_cert,
        )
        self._query_filesystem = query_filesystem

        self._log_base = "/var/log/containers"
        self._pod_base = "/var/log/pods"
        self._container_glob = "%s/*.log" % self._log_base
        self._pod_re = re.compile(r"^%s/([^/]+)/([^/]+)/.*\.log$" % self._pod_base)
        self._info_re = re.compile(
            r"^%s/([^_]+)_([^_]+)_([^_]+)-([^_]+).log$" % self._log_base
        )

    def _get_containers(
        self,
        running_or_created_after=None,
        glob_list=None,
        k8s_cache=None,
        k8s_include_by_default=True,
        k8s_namespaces_to_include=None,
        current_time=None,
    ):
        result = {}
        container_info = []

        if k8s_namespaces_to_include is None:
            k8s_namespaces_to_include = K8sNamespaceFilter.include_all()

        if current_time is None:
            current_time = time.time()

        try:
            # see if we should query the container list from the filesystem or the kubelet API
            if self._query_filesystem:
                container_info = self._get_containers_from_filesystem(
                    k8s_namespaces_to_include
                )
            else:
                container_info = self._get_containers_from_kubelet(
                    k8s_namespaces_to_include
                )

            # process the container info
            for pod_name, pod_namespace, cname, cid in container_info:
                short_cid = _get_short_cid(cid)

                # filter against the container glob list
                add_container = True
                if glob_list:
                    add_container = False
                    for glob_pattern in glob_list:
                        if fnmatch.fnmatch(cname, glob_pattern):
                            add_container = True
                            break

                if not add_container:
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_2,
                        "Excluding container '%s' based on glob_list" % short_cid,
                    )
                    continue

                # build a k8s_info structure similar to the one built by _get_containers
                k8s_info = {}
                k8s_info["pod_name"] = pod_name
                k8s_info["pod_namespace"] = pod_namespace
                k8s_info["k8s_container_name"] = cname

                # build the path to the log file on disk
                log_path = "%s/%s_%s_%s-%s.log" % (
                    self._log_base,
                    pod_name,
                    pod_namespace,
                    cname,
                    cid,
                )

                if self._query_filesystem:
                    # get pod uid from the path
                    # the log path should be a link to the /var/logs/pod/<pod_uid>/N.log
                    # so read the link.  Note, use os.readlink rather than os.path.realpath
                    # because we only want to traverse one level of links, rather than finding
                    # the eventual path on disk (which may not be the /var/logs/pod/<pod_uid>/N.log)
                    if os.path.islink(log_path):
                        link = os.readlink(log_path)
                        m = self._pod_re.match(link)
                        if m and cname == m.group(2):
                            k8s_info["pod_uid"] = m.group(1)

                # get pod and deployment/controller information for the container
                if k8s_cache:
                    pod = k8s_cache.pod(
                        pod_namespace,
                        pod_name,
                        current_time,
                        ignore_k8s_api_exception=True,
                    )
                    if pod:
                        # check to see if we should exclude this container
                        default_exclude = not k8s_include_by_default
                        exclude = pod.exclude_pod(
                            container_name=cname, default=default_exclude
                        )

                        # exclude if necessary
                        if exclude:
                            if pod.annotations:
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_2,
                                    "Excluding container '%s' based on pod annotations, %s"
                                    % (short_cid, pod.annotations),
                                )
                            continue

                        # add a debug message if containers are excluded by default but this container is included
                        if default_exclude and not exclude:
                            global_log.log(
                                scalyr_logging.DEBUG_LEVEL_2,
                                "Including container '%s' based on pod annotations, %s"
                                % (short_cid, pod.annotations),
                            )

                        k8s_info["pod_info"] = pod
                        k8s_info["pod_uid"] = pod.uid

                # add this container to the list of results
                result[cid] = {
                    "name": cname,
                    "log_path": log_path,
                    "k8s_info": k8s_info,
                }
        except Exception as e:
            global_log.error(
                "Error querying containers %s - %s"
                % (six.text_type(e), traceback.format_exc()),
                limit_once_per_x_secs=300,
                limit_key="query-cri-containers",
            )
        return result

    def _get_containers_from_filesystem(self, k8s_namespaces_to_include):

        result = []

        # iterate over all files that match our container glob
        for filename in glob.iglob(self._container_glob):

            # ignore any files that don't match the format we are expecting
            m = self._info_re.match(filename)
            if m is None:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Excluding file '%s' because the filename doesn't match the expected log format"
                    % (filename),
                )
                continue

            # extract pod and container info
            pod_name = m.group(1)
            pod_namespace = m.group(2)
            cname = m.group(3)
            cid = m.group(4)

            # ignore any unwanted namespaces
            if pod_namespace not in k8s_namespaces_to_include:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Excluding container '%s' because namespace '%s' is excluded"
                    % (cname, pod_namespace),
                )
                continue

            # ignore the scalyr-agent container
            if (
                self._ignored_pod is not None
                and pod_name == self._ignored_pod.name
                and pod_namespace == self._ignored_pod.namespace
            ):
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Excluding container because pod_name '%s' in namespace '%s' is ignored"
                    % (pod_name, pod_namespace),
                )
                continue

            result.append((pod_name, pod_namespace, cname, cid))

        return result

    def _get_containers_from_kubelet(self, k8s_namespaces_to_include):

        result = []

        try:
            # query the api
            response = self._kubelet.query_pods()
            pods = response.get("items", [])

            # process the list of pods
            for pod in pods:
                metadata = pod.get("metadata", {})
                pod_name = metadata.get("name", "")
                pod_namespace = metadata.get("namespace", "")

                # ignore anything that is in an excluded namespace
                if pod_namespace not in k8s_namespaces_to_include:
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_2,
                        "Excluding pod '%s' because namespace '%s' is excluded"
                        % (pod_name, pod_namespace),
                    )
                    continue

                # get the list of containers for this pod
                status = pod.get("status", {})
                containers = status.get("containerStatuses", [])
                for container in containers:

                    # get the id of the container
                    cid = container.get("containerID")
                    if cid is None:
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Excluding container because no cid was found",
                        )
                        continue

                    # strip out the runtime component
                    m = _CID_RE.match(cid)
                    if m:
                        cid = m.group(2)
                    else:
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Excluding container because cid didn't match expected format '<runtime>://<container id>'",
                        )
                        continue

                    short_cid = _get_short_cid(cid)

                    # ignore the scalyr-agent container
                    if (
                        self._ignored_pod is not None
                        and pod_name == self._ignored_pod.name
                        and pod_namespace == self._ignored_pod.namespace
                    ):
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Excluding container because pod_name '%s' in namespace '%s' is ignored"
                            % (pod_name, pod_namespace),
                        )
                        continue

                    # make sure the container has a name
                    cname = container.get("name")
                    if cname is None:
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Excluding container '%s' because no container name was found"
                            % short_cid,
                        )
                        continue

                    # we are only interested in running or terminated pods
                    cstate = container.get("state", {})
                    if "running" not in cstate and "terminated" not in cstate:
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Excluding container '%s' because not yet running"
                            % short_cid,
                        )
                        continue

                    result.append((pod_name, pod_namespace, cname, cid))

        except ConnectionError as e:
            global_log.error(
                "Error connecting to kubelet API endpoint - %s. The Scalyr Agent will now monitor containers from the filesystem"
                % six.text_type(e),
                limit_once_per_x_secs=300,
                limit_key="kubelet-api-connect",
            )
            self._query_filesystem = True
        except Exception:
            global_log.exception(
                "Error querying kubelet API for running pods and containers",
                limit_once_per_x_secs=300,
                limit_key="kubelet-api-query-pods",
            )

        return result


class ContainerChecker(object):
    """
        Monitors containers to check when they start and stop running.
    """

    def __init__(
        self,
        config,
        global_config,
        logger,
        socket_file,
        docker_api_version,
        agent_pod,
        host_hostname,
        log_path,
        include_all,
        include_controller_info,
        namespaces_to_include,
        ignore_pod_sandboxes,
        controlled_warmer=None,
    ):
        """
        @param config: The configuration for the monitor which includes options for the container checker
        @param global_config: The global configuration file
        @param logger: The logger instance to use
        @param socket_file: The docker socket file
        @param docker_api_version: The API version to use for docker
        @param agent_pod: The pod name and namespace for the agent
        @param host_hostname: The hostname for this node
        @param log_path: The path to the container logs
        @param include_all: Whether or not include all container by default
        @param include_controller_info: Whether or not to include the controller information for all pods upload
        @param namespaces_to_include: The namespaces whose pods should be uploaded.
        @param ignore_pod_sandboxes: Whether or not to recognize pod sandboxes
        @param controlled_warmer: If the pod cache should be proactively warmed using the controlled
            cache warmer strategy, the instance to use.
        @type config: dict
        @type global_config: Configuration
        @type logger: Logger
        @type socket_file: str
        @type docker_api_version: str
        @type agent_pod: QualifiedName
        @type host_hostname: str
        @type log_path: str
        @type include_all: bool
        @type include_controller_info: bool
        @type namespaces_to_include: [K8sNamespaceFilter]
        @type ignore_pod_sandboxes: bool
        @type controlled_warmer: ControlledCacheWarmer or None
        """
        self._config = config
        self._global_config = global_config
        self._logger = logger

        self.__delay = self._config.get("container_check_interval")
        self.__name = self._config.get("container_name")

        self.__use_v2_attributes = self._config.get("k8s_use_v2_attributes")
        self.__use_v1_and_v2_attributes = self._config.get(
            "k8s_use_v1_and_v2_attributes"
        )

        # get the format for parsing logs
        self.__parse_format = self._config.get("k8s_parse_format")

        # if the deprecated `k8s_parse_json` flag is set, that should override
        # the `k8s_parse_format` option on the basis that it would be a left over
        # value from an older configuration file and we want to maintain similar behavior
        parse_json = self._config.get("k8s_parse_json")
        if parse_json is not None:
            if parse_json:
                self.__parse_format = "auto"
            else:
                self.__parse_format = "raw"

        self.__socket_file = socket_file
        self.__docker_api_version = docker_api_version
        self.__client = None
        self.__always_use_cri = self._config.get("k8s_always_use_cri")
        self.__always_use_docker = self._config.get("k8s_always_use_docker")
        self.__cri_query_filesystem = self._config.get("k8s_cri_query_filesystem")
        self.__sidecar_mode = self._config.get("k8s_sidecar_mode")

        self.__k8s_log_configs = self._global_config.k8s_log_configs

        self.__agent_pod = agent_pod

        self.__log_path = log_path

        self.__host_hostname = host_hostname

        self.__readback_buffer_size = self._config.get("readback_buffer_size")

        self.__glob_list = config.get("container_globs")

        # The namespaces of pods whose containers we should return.
        self.__namespaces_to_include = namespaces_to_include

        self.__ignore_pod_sandboxes = ignore_pod_sandboxes

        # This is currently an experimental feature.  Including controller information for every event uploaded about
        # a pod (cluster name, controller name, controller labels)
        self.__include_controller_info = include_controller_info

        self.containers = {}
        self.__include_all = include_all

        self.__k8s_cache_init_abort_delay = self._config.get(
            "k8s_cache_init_abort_delay"
        )

        self.k8s_cache = None
        self.__k8s_config_builder = None

        self.__node_name = None

        self.__log_watcher = None
        self.__module = None
        self.__start_time = time.time()
        self.__thread = StoppableThread(
            target=self.check_containers, name="Container Checker"
        )
        self._container_enumerator = None
        self._container_runtime = "unknown"
        self.__controlled_warmer = controlled_warmer

        # give this an initial empty value
        self.raw_logs = []

    def _is_running_in_docker(self):
        """
        Checks to see if the agent is running inside a docker container
        """
        # whether or not we are running inside docker can be determined
        # by the existence of the file /.dockerenv
        return os.path.exists("/.dockerenv")

    def get_cluster_name(self, k8s_cache):
        """ Gets the cluster name that the agent is running on """
        cluster_name = compat.os_environ_unicode.get("SCALYR_K8S_CLUSTER_NAME")
        if cluster_name is not None:
            # 2->TODO in python2 os.getenv returns 'str' type. Convert it to unicode.
            cluster_name = six.ensure_text(cluster_name)
            return cluster_name

        return (k8s_cache and k8s_cache.get_cluster_name()) or None

    def _get_node_name(self):
        """ Gets the node name of the node running the agent from downward API """
        # 2->TODO in python2 os.getenv returns 'str' type. Convert it to unicode.
        node_name = compat.os_environ_unicode.get("SCALYR_K8S_NODE_NAME")
        if node_name is not None:
            node_name = six.ensure_text(node_name)
        return node_name

    def _get_pod_name(self):
        """ Gets the pod name of the pod running the agent from downward API"""
        # 2->TODO in python2 os.getenv returns 'str' type. Convert it to unicode.
        pod_name = compat.os_environ_unicode.get("SCALYR_K8S_POD_NAME")
        if pod_name is not None:
            pod_name = six.ensure_text(pod_name)
        return pod_name

    def _get_container_runtime(self):
        """ Gets the container runtime currently in use """
        if not self.k8s_cache:
            global_log.warning(
                "Coud not determine K8s CRI because no k8 cache.",
                limit_once_per_x_secs=300,
                limit_key="k8s_cri_no_cache",
            )
        return (self.k8s_cache and self.k8s_cache.get_container_runtime()) or "unknown"

    def start(self):

        try:
            k8s_api_url = self._global_config.k8s_api_url
            self._config.get("k8s_verify_api_queries")

            # create the k8s cache
            self.k8s_cache = k8s_utils.cache(self._global_config)

            # TODO: Uncomment after the v59 release.  This is a bit of a risky change that needs more testing
            # to ensure we do not hurt some class of customers.
            # self.__verify_service_account()

            if self.__controlled_warmer is not None:
                self.__controlled_warmer.set_k8s_cache(self.k8s_cache)
                self.__controlled_warmer.start()

            delay = 0.5
            message_delay = 5
            start_time = time.time()
            message_time = start_time

            # wait until the k8s_cache is initialized before aborting
            while not self.k8s_cache.is_initialized():
                time.sleep(delay)
                current_time = time.time()
                last_initialization_error = self.k8s_cache.last_initialization_error()
                if last_initialization_error is not None:
                    # see if we need to abort the monitor because we've been waiting too long for init
                    if current_time - start_time > self.__k8s_cache_init_abort_delay:
                        raise K8sInitException(
                            "Kubernetes monitor failed to start due to cache initialization error: %s"
                            % last_initialization_error
                        )

                    # see if we need to print a message
                    if current_time - message_time > message_delay:
                        self._logger.warning(
                            "Kubernetes monitor not started yet (will retry) due to error in cache initialization %s",
                            last_initialization_error,
                        )
                        message_time = current_time

            # check to see if the user has manually specified a cluster name, and if so then
            # force enable 'Starbuck' features
            if self.get_cluster_name(self.k8s_cache) is not None:
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "ContainerChecker - cluster name detected, enabling v2 attributes and controller information",
                )
                self.__use_v2_attributes = True
                self.__include_controller_info = True

            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_2,
                "Attempting to retrieve list of containers:",
            )

            self.__node_name = self._get_node_name() or "unknown node"
            self._container_runtime = self._get_container_runtime()
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Container runtime is '%s'" % (self._container_runtime),
            )

            if self.__always_use_docker or (
                self._container_runtime == "docker" and not self.__always_use_cri
            ):
                global_log.info(
                    "kubernetes_monitor is using docker for listing containers"
                )
                self.__client = DockerClient(
                    base_url=("unix:/%s" % self.__socket_file),
                    version=self.__docker_api_version,
                )
                self._container_enumerator = DockerEnumerator(
                    self.__client,
                    self.__agent_pod,
                    controlled_warmer=self.__controlled_warmer,
                    is_sidecar_mode=self.__sidecar_mode,
                )
            else:
                query_fs = self.__cri_query_filesystem
                global_log.info(
                    "kubernetes_monitor is using CRI with fs=%s for listing containers"
                    % six.text_type(query_fs)
                )
                self._container_enumerator = CRIEnumerator(
                    self._global_config,
                    self.__agent_pod,
                    k8s_api_url,
                    query_fs,
                    self._get_node_name(),
                    self._config.get("k8s_kubelet_host_ip"),
                    self._config.get("k8s_kubelet_api_url_template"),
                    is_sidecar_mode=self.__sidecar_mode,
                )

            if self.__parse_format == "auto":
                # parse in json if we detect the container runtime to be 'docker' or if we detect
                # that we are running in docker
                if self._container_runtime == "docker" or self._is_running_in_docker():
                    self.__parse_format = "json"
                else:
                    self.__parse_format = "cri"

            self.containers = self._container_enumerator.get_containers(
                glob_list=self.__glob_list,
                k8s_cache=self.k8s_cache,
                k8s_include_by_default=self.__include_all,
                k8s_namespaces_to_include=self.__namespaces_to_include,
            )

            # Create the k8s config builder
            rename_no_original = False
            # This is for a hack to prevent the original log file name from being added to the attributes.
            if self.__use_v2_attributes and not self.__use_v1_and_v2_attributes:
                rename_no_original = True
            self.__k8s_config_builder = K8sConfigBuilder(
                self._global_config.k8s_log_configs,
                self._logger,
                rename_no_original,
                parse_format=self.__parse_format,
            )

            # if querying the docker api fails, set the container list to empty
            if self.containers is None:
                self.containers = {}

            self.raw_logs = []

            self.docker_logs = self.__get_docker_logs(self.containers, self.k8s_cache)

            # create and start the DockerLoggers
            self.__start_docker_logs(self.docker_logs)
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Initialization complete.  Starting k8s monitor for Scalyr",
            )
            self.__thread.start()

        except K8sInitException as e:
            e_as_text = six.text_type(e)
            global_log.warn(
                "Failed to start container checker - %s. Aborting kubernetes_monitor"
                % e_as_text
            )
            k8s_utils.terminate_agent_process(getattr(e, "message", e_as_text))
            raise
        except Exception as e:
            global_log.warn(
                "Failed to start container checker - %s\n%s"
                % (six.text_type(e), traceback.format_exc())
            )

    def stop(self, wait_on_join=True, join_timeout=5):
        if self.__controlled_warmer is not None:
            self.__controlled_warmer.stop(
                wait_on_join=wait_on_join, join_timeout=join_timeout
            )

        self.__thread.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

        self.raw_logs = []

    def get_k8s_data(self):
        """ Convenience wrapper to query and process all pods
            and pods retreived by the k8s API.
            A filter is used to limit pods returned to those that
            are running on the current node

            @return: a dict keyed by namespace, whose values are a dict of pods inside that namespace, keyed by pod name
        """
        result = {}
        try:
            result = self.k8s_cache.pods_shallow_copy()
        except Exception as e:
            global_log.warn(
                "Failed to get k8s data: %s\n%s"
                % (six.text_type(e), traceback.format_exc()),
                limit_once_per_x_secs=300,
                limit_key="get_k8s_data",
            )
        return result

    def check_containers(self, run_state):
        """Update thread for monitoring docker containers and the k8s info such as labels
        """

        # Assert that the cache has been initialized
        if not self.k8s_cache.is_initialized():
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "container_checker - Kubernetes cache not initialized",
            )
            raise K8sInitException(
                "check_container - Kubernetes cache not initialized. Aborting"
            )

        # store the digests from the previous iteration of the main loop to see
        # if any pod information has changed
        prev_digests = {}
        base_attributes = self.__get_base_attributes()
        previous_time = time.time()

        while run_state.is_running():
            try:

                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Attempting to retrieve list of containers:",
                )

                current_time = time.time()

                running_containers = self._container_enumerator.get_containers(
                    running_or_created_after=previous_time,
                    glob_list=self.__glob_list,
                    k8s_cache=self.k8s_cache,
                    k8s_include_by_default=self.__include_all,
                    k8s_namespaces_to_include=self.__namespaces_to_include,
                    current_time=current_time,
                )

                previous_time = current_time - 1

                # if running_containers is None, that means querying the docker api failed.
                # rather than resetting the list of running containers to empty
                # continue using the previous list of containers
                if running_containers is None:
                    self._logger.log(
                        scalyr_logging.DEBUG_LEVEL_2, "Failed to get list of containers"
                    )
                    running_containers = self.containers

                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Found %d containers" % len(running_containers),
                )
                # get the containers that have started since the last sample
                starting = {}
                changed = {}
                digests = {}

                for cid, info in six.iteritems(running_containers):
                    pod = None
                    if "k8s_info" in info:
                        pod = info["k8s_info"].get("pod_info", None)

                        if not pod:
                            pass
                            # Don't log any warnings here for now
                            # pod_name = info["k8s_info"].get("pod_name", "invalid_pod")
                            # pod_namespace = info["k8s_info"].get(
                            #     "pod_namespace", "invalid_namespace"
                            # )
                            # self._logger.warning( "No pod info for container %s.  pod: '%s/%s'" % (_get_short_cid( cid ), pod_namespace, pod_name),
                            #                      limit_once_per_x_secs=300,
                            #                      limit_key='check-container-pod-info-%s' % cid)

                    # start the container if have a container that wasn't running
                    if cid not in self.containers:
                        self._logger.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "Starting loggers for container '%s'" % info["name"],
                        )
                        starting[cid] = info
                    elif cid in prev_digests:
                        # container was running and it exists in the previous digest dict, so see if
                        # it has changed
                        if pod and prev_digests[cid] != pod.digest:
                            self._logger.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "Pod digest changed for '%s'" % info["name"],
                            )
                            changed[cid] = info

                    # store the digest from this iteration of the loop
                    if pod:
                        digests[cid] = pod.digest

                # get the containers that have stopped
                stopping = {}
                for cid, info in six.iteritems(self.containers):
                    if cid not in running_containers:
                        self._logger.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "Stopping logger for container '%s' (%s)"
                            % (info["name"], cid[:6]),
                        )
                        stopping[cid] = info

                # stop the old loggers
                self.__stop_loggers(stopping)

                # update the list of running containers
                # do this before starting new ones, as starting up new ones
                # will access self.containers
                self.containers = running_containers

                # start the new ones
                self.__start_loggers(starting, self.k8s_cache)

                prev_digests = digests

                # update the log config for any changed containers
                if self.__log_watcher:
                    for logger in self.raw_logs:
                        if logger["cid"] in changed:
                            info = changed[logger["cid"]]
                            new_config = self.__get_log_config_for_container(
                                logger["cid"], info, self.k8s_cache, base_attributes
                            )
                            self._logger.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "updating config for '%s'" % info["name"],
                            )
                            self.__log_watcher.update_log_config(
                                self.__module.module_name, new_config
                            )
            except Exception as e:
                self._logger.warn(
                    "Exception occurred when checking containers %s\n%s"
                    % (six.text_type(e), traceback.format_exc())
                )

            run_state.sleep_but_awaken_if_stopped(self.__delay)

    def set_log_watcher(self, log_watcher, module):
        self.__log_watcher = log_watcher
        self.__module = module

    def __stop_loggers(self, stopping):
        """
        Stops any DockerLoggers in the 'stopping' dict
        @param stopping:  a dict of container ids => container names. Any running containers that have
        the same container-id as a key in the dict will be stopped.
        """
        if stopping:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_2, "Stopping all docker loggers"
            )

            # go through all the raw logs and see if any of them exist in the stopping list, and if so, stop them
            for logger in self.raw_logs:
                cid = logger["cid"]
                if cid in stopping:
                    path = logger["log_config"]["path"]
                    if self.__log_watcher:
                        self.__log_watcher.schedule_log_path_for_removal(
                            self.__module.module_name, path
                        )

            self.raw_logs[:] = [l for l in self.raw_logs if l["cid"] not in stopping]
            self.docker_logs[:] = [
                l for l in self.docker_logs if l["cid"] not in stopping
            ]

    def __start_loggers(self, starting, k8s_cache):
        """
        Starts a list of DockerLoggers
        @param starting:  a list of DockerLoggers to start
        """
        if starting:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_2, "Starting all docker loggers"
            )
            docker_logs = self.__get_docker_logs(starting, k8s_cache)
            self.__start_docker_logs(docker_logs)
            self.docker_logs.extend(docker_logs)

    def __start_docker_logs(self, docker_logs):
        for log in docker_logs:
            if self.__log_watcher:
                log["log_config"] = self.__log_watcher.add_log_config(
                    self.__module.module_name, log["log_config"]
                )

            self.raw_logs.append(log)

    def __get_last_request_for_log(self, path):
        result = datetime.datetime.fromtimestamp(self.__start_time)

        try:
            full_path = os.path.join(self.__log_path, path)
            fp = open(full_path, "r", self.__readback_buffer_size)

            # seek readback buffer bytes from the end of the file
            fp.seek(0, os.SEEK_END)
            size = fp.tell()
            if size < self.__readback_buffer_size:
                fp.seek(0, os.SEEK_SET)
            else:
                fp.seek(size - self.__readback_buffer_size, os.SEEK_SET)

            first = True
            for line in fp:
                # ignore the first line because it likely started somewhere randomly
                # in the line
                if first:
                    first = False
                    continue

                dt, _ = _split_datetime_from_line(line)
                if dt:
                    result = dt
            fp.close()
        except Exception as e:
            global_log.info("%s", six.text_type(e))

        return scalyr_util.seconds_since_epoch(result)

    def __get_base_attributes(self):
        attributes = None
        try:
            attributes = JsonObject({"monitor": "agentKubernetes"})
            if self.__host_hostname:
                attributes["serverHost"] = self.__host_hostname

        except Exception:
            self._logger.error("Error setting monitor attribute in KubernetesMonitor")
            raise

        return attributes

    def __get_log_config_for_container(self, cid, info, k8s_cache, base_attributes):
        result = None

        container_attributes = base_attributes.copy()
        if not self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
            container_attributes["containerName"] = info["name"]
            container_attributes["containerId"] = cid
        elif self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
            container_attributes["container_id"] = cid

        parser = "docker"
        common_annotations = {}
        container_annotations = {}
        # pod name and namespace are set to an invalid value for cases where errors occur and a log
        # message is produced, so that the log message has clearly invalid values for these rather
        # than just being empty
        pod_name = "--"
        pod_namespace = "--"
        short_cid = _get_short_cid(cid)

        # dict of available substitutions for the rename_logfile field
        rename_vars = {
            "short_id": short_cid,
            "container_id": cid,
            "container_name": info["name"],
            "container_runtime": self._container_runtime,
        }

        k8s_info = info.get("k8s_info", {})

        if k8s_info:
            pod_name = k8s_info.get("pod_name", "invalid_pod")
            pod_namespace = k8s_info.get("pod_namespace", "invalid_namespace")
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "got k8s info for container %s, '%s/%s'"
                % (short_cid, pod_namespace, pod_name),
            )

            rename_vars["pod_name"] = pod_name
            rename_vars["namespace"] = pod_namespace
            rename_vars["pod_namespace"] = pod_namespace
            container_attributes["pod_name"] = pod_name
            container_attributes["pod_namespace"] = pod_namespace

            # get the cluster name
            cluster_name = self.get_cluster_name(k8s_cache)
            if self.__include_controller_info and cluster_name is not None:
                container_attributes["_k8s_cn"] = cluster_name

            pod = k8s_cache.pod(pod_namespace, pod_name, ignore_k8s_api_exception=True)
            if pod:
                rename_vars["node_name"] = pod.node_name

                container_attributes["scalyr-category"] = "log"
                container_attributes["pod_uid"] = pod.uid

                if not self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
                    container_attributes["node_name"] = pod.node_name
                elif self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
                    container_attributes["k8s_node"] = pod.node_name

                for label, value in six.iteritems(pod.labels):
                    container_attributes[label] = value

                if "parser" in pod.labels:
                    parser = pod.labels["parser"]

                # get the controller information if any
                if pod.controller is not None:
                    controller = pod.controller
                    # for backwards compatibility allow both deployment_name and controller_name here
                    rename_vars["deployment_name"] = controller.name
                    rename_vars["controller_name"] = controller.name
                    if self.__include_controller_info:
                        container_attributes["_k8s_dn"] = controller.name
                        container_attributes["_k8s_dl"] = controller.flat_labels
                        container_attributes["_k8s_ck"] = controller.kind

                # get the annotations of this pod as a dict.
                # by default all annotations will be applied to all containers
                # in the pod
                all_annotations = pod.annotations
                container_specific_annotations = False

                # get any common annotations for all containers
                for annotation, value in six.iteritems(all_annotations):
                    if annotation in pod.container_names:
                        container_specific_annotations = True
                    else:
                        common_annotations[annotation] = value

                # now get any container specific annotations
                # for this container
                if container_specific_annotations:
                    k8s_container_name = k8s_info.get("k8s_container_name", "")
                    if k8s_container_name in all_annotations:
                        # get the annotations for this container
                        container_annotations = all_annotations[k8s_container_name]

                        # sanity check to make sure annotations are either a JsonObject or dict
                        if not isinstance(
                            container_annotations, JsonObject
                        ) and not isinstance(container_annotations, dict):
                            self._logger.warning(
                                "Unexpected configuration found in annotations for pod '%s/%s'.  Expected a dict for configuration of container '%s', but got a '%s' instead. No container specific configuration options applied."
                                % (
                                    pod.namespace,
                                    pod.name,
                                    k8s_container_name,
                                    six.text_type(type(container_annotations)),
                                ),
                                limit_once_per_x_secs=300,
                                limit_key="k8s-invalid-container-config-%s" % cid,
                            )
                            container_annotations = {}

            else:
                self._logger.warning(
                    "Couldn't map container '%s' to pod '%s/%s'. Logging limited metadata from docker container labels instead."
                    % (short_cid, pod_namespace, pod_name),
                    limit_once_per_x_secs=300,
                    limit_key="k8s-docker-mapping-%s" % cid,
                )
                container_attributes["pod_name"] = pod_name
                container_attributes["pod_namespace"] = pod_namespace
                container_attributes["pod_uid"] = k8s_info.get("pod_uid", "invalid_uid")
                container_attributes["k8s_container_name"] = k8s_info.get(
                    "k8s_container_name", "invalid_container_name"
                )
        else:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1, "no k8s info for container %s" % short_cid
            )

        result = self.__k8s_config_builder.get_log_config(
            info=info, k8s_info=k8s_info, parser=parser,
        )

        if result is None:
            # without a log_path there is no log config that can be created.  Log a warning and return
            # See ticket: #AGENT-88
            self._logger.warning(
                "No log path found for container '%s' of %s/%s"
                % (short_cid, pod_namespace, pod_name),
                limit_once_per_x_secs=3600,
                limit_key="k8s-invalid-log-path-%s" % short_cid,
            )
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Info is: %s\nCommon annotations: %s\nContainer annotations: %s"
                % (info, common_annotations, container_annotations),
                limit_once_per_x_secs=3600,
                limit_key="k8s-invalid-log-path-info-%s" % short_cid,
            )

            return None

        if "k8s_container_name" in k8s_info:
            rename_vars["k8s_container_name"] = k8s_info["k8s_container_name"]

        # Annotation override all other configs:
        # apply common annotations first
        annotations = common_annotations
        # set/override any container specific annotations
        annotations.update(container_annotations)

        # ignore include/exclude options which have special
        # handling in the log_config verification that expects a different type than the one used in the nnotations
        skip_keys = ["include", "exclude"]

        # list of config items that cannot be updated via annotations
        invalid_keys = ["path", "lineGroupers"]

        # set config items, ignoring invalid options
        for key, value in six.iteritems(annotations):
            if key in skip_keys:
                continue

            if key in invalid_keys:
                self._logger.warning(
                    "Invalid key '%s' found in annotation config for '%s/%s'. Configuration of '%s' is not currently supported via annotations and has been ignored."
                    % (key, pod_namespace, pod_name, key),
                    limit_once_per_x_secs=300,
                    limit_key="k8s-invalid-annotation-config-key-%s" % key,
                )
                continue

            # everything else is added to the log_config result as is
            result[key] = value

        # Perform variable substitution for rename_logfile
        if "rename_logfile" in result:
            template = Template(result["rename_logfile"])
            result["rename_logfile"] = template.safe_substitute(rename_vars)

        # Update result["attributes"] with list of attributes generated by the agent
        # Make sure to use a copy because it could be pointing to objects in the original attributes
        # or log configs, and we don't want to modify those
        attrs = result.get("attributes", JsonObject({})).copy()
        for key, value in six.iteritems(container_attributes):
            # Only set values that haven't been explicity set
            # by an annotation or k8s_logs config option
            if key not in attrs:
                attrs[key] = value

        # use our new copy instead
        result["attributes"] = attrs

        # Update root level parser if attributes["parser"] is set
        if "parser" in attrs:
            result["parser"] = attrs["parser"]

        return result

    def __get_docker_logs(self, containers, k8s_cache):
        """Returns a list of dicts containing the container id, stream, and a log_config
        for each container in the 'containers' param.
        """

        result = []

        attributes = self.__get_base_attributes()

        for cid, info in six.iteritems(containers):
            log_config = self.__get_log_config_for_container(
                cid, info, k8s_cache, attributes
            )
            if log_config:
                result.append({"cid": cid, "stream": "raw", "log_config": log_config})

        return result

    def __verify_service_account(self):
        """
        Verifies that the appropriate service account information can be read from the pod, otherwise raises
        a `K8sInitException`.  This is meant to catch common configuration issues.
        """
        if self._global_config.k8s_verify_api_queries and not (
            os.path.isfile(self._global_config.k8s_service_account_cert)
            and os.access(self._global_config.k8s_service_account_cert, os.R_OK)
        ):
            raise K8sInitException(
                "Service account certificate not found at '%s'.  Be sure "
                "'automountServiceAccountToken' is set to True"
            )


class KubernetesMonitor(
    ScalyrMonitor
):  # pylint: disable=monitor-not-included-for-win32
    """
# Kubernetes Monitor

This monitor is based of the docker_monitor plugin, and uses the raw logs mode of the docker
plugin to send Kubernetes logs to Scalyr.  It also reads labels from the Kubernetes API and
associates them with the appropriate logs.

## Log Config via Annotations

The logs collected by the Kubernetes monitor can be configured via k8s pod annotations.
The monitor examines all annotations on all pods, and for any annotation that begins with the
prefix log.config.scalyr.com/, it extracts the
entries (minus the prefix) and maps them to the log_config stanza for that pod's containers.
The mapping is described below.

The following fields can be configured a log via pod annotations:

* parser
* attributes
* sampling_rules
* rename_logfile
* redaction_rules

These behave in the same way as specified in the main [Scalyr help
docs](https://www.scalyr.com/help/scalyr-agent#logUpload). The following configuration
fields behave differently when configured via k8s annotations:

* exclude (see below)
* lineGroupers (not supported at all)
* path (the path is always fixed for k8s container logs)

### Excluding Logs

Containers and pods can be specifically included/excluded from having their logs collected and
sent to Scalyr.  Unlike the normal log_config `exclude` option which takes an array of log path
exclusion globs, annotations simply support a Boolean true/false for a given container/pod.
Both `include` and `exclude` are supported, with `include` always overriding `exclude` if both
are set. e.g.

    log.config.scalyr.com/exclude: true

has the same effect as

    log.config.scalyr.com/include: false

By default the agent monitors the logs of all pods/containers, and you have to manually exclude
pods/containers you don't want.  You can also set `k8s_include_all_containers: false` in the
kubernetes_monitor monitor config section of `agent.d/docker.json`, in which case all containers are
excluded by default and have to be manually included.

### Specifying Config Options

The Kubernetes monitor takes the string value of each annotation and maps it to a dict, or
array value according to the following format:

Values separated by a period are mapped to dict keys e.g. if one annotation on a given pod was
specified as:

        log.config.scalyr.com/attributes.parser: accessLog

Then this would be mapped to the following dict, which would then be applied to the log config
for all containers in that pod:

    { "attributes": { "parser": "accessLog" } }

Arrays can be specified by using one or more digits as the key, e.g. if the annotation was

        log.config.scalyr.com/sampling_rules.0.match_expression: INFO
        log.config.scalyr.com/sampling_rules.0.sampling_rate: 0.1
        log.config.scalyr.com/sampling_rules.1.match_expression: FINE
        log.config.scalyr.com/sampling_rules.1.sampling_rate: 0

This will be mapped to the following structure:

    { "sampling_rules":
        [
        { "match_expression": "INFO", "sampling_rate": 0.1 },
        { "match_expression": "FINE", "sampling_rate": 0 }
        ]
    }

Array keys are sorted by numeric order before processing and unique objects need to have
different digits as the array key. If a sub-key has an identical array key as a previously seen
sub-key, then the previous value of the sub-key is overwritten

There is no guarantee about the order of processing for items with the same numeric array key,
so if the config was specified as:

        log.config.scalyr.com/sampling_rules.0.match_expression: INFO
        log.config.scalyr.com/sampling_rules.0.match_expression: FINE

It is not defined or guaranteed what the actual value will be (INFO or FINE).

### Applying config options to specific containers in a pod

If a pod has multiple containers and you only want to apply log configuration options to a
specific container you can do so by prefixing the option with the container name, e.g. if you
had a pod with two containers `nginx` and `helper1` and you wanted to exclude `helper1` logs you
could specify the following annotation:

    log.config.scalyr.com/helper1.exclude: true

Config items specified without a container name are applied to all containers in the pod, but
container specific settings will override pod-level options, e.g. in this example:

    log.config.scalyr.com/exclude: true
    log.config.scalyr.com/nginx.include: true

All containers in the pod would be excluded *except* for the nginx container, which is included.

This technique is applicable for all log config options, not just include/exclude.  For
example you could set the line sampling rules for all containers in a pod, but use a different set
of line sampling rules for one specific container in the pod if needed.

### Dynamic Updates

Currently all annotation config options except `exclude: true`/`include: false` can be
dynamically updated using the `kubectl annotate` command.

For `exclude: true`/`include: false` once a pod/container has started being logged, then while the
container is still running, there is currently no way to dynamically start/stop logging of that
container using annotations without updating the config yaml, and applying the updated config to the
cluster.
    """

    def __get_socket_file(self):
        """Gets the Docker API socket file and validates that it is a UNIX socket
        """
        # make sure the API socket exists and is a valid socket
        api_socket = self._config.get("api_socket")
        try:
            st = os.stat(api_socket)
            if not stat.S_ISSOCK(st.st_mode):
                raise Exception()
        except Exception:
            raise Exception(
                "The file '%s' specified by the 'api_socket' configuration option does not exist or is not a socket.\n\tPlease make sure you have mapped the docker socket from the host to this container using the -v parameter.\n\tNote: Due to problems Docker has mapping symbolic links, you should specify the final file and not a path that contains a symbolic link, e.g. map /run/docker.sock rather than /var/run/docker.sock as on many unices /var/run is a symbolic link to the /run directory."
                % api_socket
            )

        return api_socket

    def _set_namespaces_to_include(self):
        """This function is separated out for better testability
        (consider generalizing this method to support other k8s_monitor config params that are overridden globally)
        """
        self.__namespaces_to_include = K8sNamespaceFilter.from_config(
            global_config=self._global_config, local_config=self._config
        )

    def _get_namespaces_to_include(self):
        return self.__namespaces_to_include

    def _initialize(self):
        """This method gets called every 30 seconds regardless"""
        log_path = ""
        host_hostname = ""

        # Since getting metrics from Docker takes a non-trivial amount of time, we will deduct the time spent
        # in gathering the metric samples from the time we should sleep so that we do gather a sample once every
        # sample_interval_secs
        self._adjust_sleep_by_gather_time = True

        # Override the default value for the rate limit for writing the metric logs.  We override it to set no limit
        # because it is fairly difficult to bound this since the log will emit X metrics for every pod being monitored.
        self._log_write_rate = self._config.get(
            "monitor_log_write_rate", convert_to=int, default=-1
        )
        self._log_max_write_burst = self._config.get(
            "monitor_log_max_write_burst", convert_to=int, default=-1
        )

        if self._global_config:
            log_path = self._global_config.agent_log_path

            if self._global_config.server_attributes:
                if "serverHost" in self._global_config.server_attributes:
                    host_hostname = self._global_config.server_attributes["serverHost"]
                else:
                    self._logger.info("no server host in server attributes")
            else:
                self._logger.info("no server attributes in global config")

        parse_format = self._config.get("k8s_parse_format")
        if parse_format not in ["auto", "raw", "json", "cri"]:
            raise BadMonitorConfiguration(
                "k8s_parse_format must be one of 'auto', 'json', 'cri' or 'raw'.  Current value is: %s"
                % parse_format,
                "k8s_parse_format",
            )

        self._set_namespaces_to_include()

        self.__ignore_pod_sandboxes = self._config.get("k8s_ignore_pod_sandboxes")
        self.__socket_file = self.__get_socket_file()
        self.__docker_api_version = self._config.get("docker_api_version")
        self.__k8s_api_url = self._global_config.k8s_api_url
        self.__docker_max_parallel_stats = self._config.get("docker_max_parallel_stats")
        self.__client = None
        self.__metric_fetcher = None

        self.__glob_list = self._config.get("container_globs")
        self.__include_all = self._config.get("k8s_include_all_containers")

        self.__report_container_metrics = self._config.get("report_container_metrics")
        self.__report_k8s_metrics = (
            self._config.get("report_k8s_metrics") and self.__report_container_metrics
        )
        self.__percpu_metrics = self._config.get("docker_percpu_metrics")
        # Object for talking to the kubelet server running on this localhost.  This is used to gather metrics only
        # available via the kubelet.
        self.__kubelet_api = None
        self.__gather_k8s_pod_info = self._config.get("gather_k8s_pod_info")

        # Including controller information for every event uploaded about  a pod (cluster name, controller name,
        # controller labels)
        self.__include_controller_info = self._config.get(
            "include_deployment_info", convert_to=bool, default=False
        )

        # Throw BadMonitorConfiguration if any of these required environment variables is not set.
        self.__verify_required_env_var("SCALYR_K8S_POD_NAME")
        self.__verify_required_env_var("SCALYR_K8S_POD_NAMESPACE")
        self.__verify_required_env_var("SCALYR_K8S_NODE_NAME")

        # 2->TODO in python2 os.getenv returns 'str' type. Convert it to unicode.
        pod_namespace = compat.os_getenv_unicode("SCALYR_K8S_POD_NAMESPACE")
        pod_name = compat.os_getenv_unicode("SCALYR_K8S_POD_NAME")

        self.__agent_pod = QualifiedName(pod_namespace, pod_name)

        # create controlled cache warmers for logs and metrics
        self.__logs_controlled_warmer = ControlledCacheWarmer(
            max_failure_count=self._global_config.k8s_controlled_warmer_max_attempts,
            blacklist_time_secs=self._global_config.k8s_controlled_warmer_blacklist_time,
            max_query_retries=self._global_config.k8s_controlled_warmer_max_query_retries,
            logger=global_log,
        )

        self.__metrics_controlled_warmer = ControlledCacheWarmer(
            max_failure_count=self._global_config.k8s_controlled_warmer_max_attempts,
            blacklist_time_secs=self._global_config.k8s_controlled_warmer_blacklist_time,
            max_query_retries=self._global_config.k8s_controlled_warmer_max_query_retries,
            logger=global_log,
        )

        self.__container_checker = None
        if self._config.get("log_mode") != "syslog":
            self.__container_checker = ContainerChecker(
                self._config,
                self._global_config,
                self._logger,
                self.__socket_file,
                self.__docker_api_version,
                self.__agent_pod,
                host_hostname,
                log_path,
                self.__include_all,
                self.__include_controller_info,
                self.__namespaces_to_include,
                self.__ignore_pod_sandboxes,
                controlled_warmer=self.__logs_controlled_warmer,
            )

        # Metrics provided by the kubelet API.
        self.__k8s_pod_network_metrics = {
            "k8s.pod.network.rx_bytes": "rxBytes",
            "k8s.pod.network.rx_errors": "rxErrors",
            "k8s.pod.network.tx_bytes": "txBytes",
            "k8s.pod.network.tx_errors": "txErrors",
        }

        # Metrics provide by the kubelet API.
        self.__k8s_node_network_metrics = {
            "k8s.node.network.rx_bytes": "rxBytes",
            "k8s.node.network.rx_errors": "rxErrors",
            "k8s.node.network.tx_bytes": "txBytes",
            "k8s.node.network.tx_errors": "txErrors",
        }

        # All the docker. metrics are provided by the docker API.
        self.__network_metrics = self.__build_metric_dict(
            "docker.net.",
            [
                "rx_bytes",
                "rx_dropped",
                "rx_errors",
                "rx_packets",
                "tx_bytes",
                "tx_dropped",
                "tx_errors",
                "tx_packets",
            ],
        )

        self.__mem_stat_metrics = self.__build_metric_dict(
            "docker.mem.stat.",
            [
                "total_pgmajfault",
                "cache",
                "mapped_file",
                "total_inactive_file",
                "pgpgout",
                "rss",
                "total_mapped_file",
                "writeback",
                "unevictable",
                "pgpgin",
                "total_unevictable",
                "pgmajfault",
                "total_rss",
                "total_rss_huge",
                "total_writeback",
                "total_inactive_anon",
                "rss_huge",
                "hierarchical_memory_limit",
                "total_pgfault",
                "total_active_file",
                "active_anon",
                "total_active_anon",
                "total_pgpgout",
                "total_cache",
                "inactive_anon",
                "active_file",
                "pgfault",
                "inactive_file",
                "total_pgpgin",
            ],
        )

        self.__mem_metrics = self.__build_metric_dict(
            "docker.mem.", ["max_usage", "usage", "fail_cnt", "limit"]
        )

        self.__cpu_usage_metrics = self.__build_metric_dict(
            "docker.cpu.", ["usage_in_usermode", "total_usage", "usage_in_kernelmode"]
        )

        self.__cpu_throttling_metrics = self.__build_metric_dict(
            "docker.cpu.throttling.", ["periods", "throttled_periods", "throttled_time"]
        )

    def set_log_watcher(self, log_watcher):
        """Provides a log_watcher object that monitors can use to add/remove log files
        """
        if self.__container_checker:
            self.__container_checker.set_log_watcher(log_watcher, self)

    def __build_metric_dict(self, prefix, names):
        result = {}
        for name in names:
            result["%s%s" % (prefix, name)] = name
        return result

    def __verify_required_env_var(self, env_var_name):
        if len(compat.os_environ_unicode.get(env_var_name, "")) == 0:
            self._logger.error(
                "ERROR: Missing required environment variable for kubenetes_monitor: %s"
                % env_var_name
            )
            self._logger.error(
                "Please restart with up-to-date Scalyr Agent Daemonset manifest (YAML) file."
            )
            raise BadMonitorConfiguration(
                'Required environment variable "%s" is not set for kubernetes_monitor.'
                % env_var_name,
                env_var_name,
            )

    def __log_metrics(self, monitor_override, metrics_to_emit, metrics, extra=None):
        if metrics is None:
            return

        for key, value in six.iteritems(metrics_to_emit):
            if value in metrics:
                # Note, we do a bit of a hack to pretend the monitor's name include the container/pod's name.  We take this
                # approach because the Scalyr servers already have some special logic to collect monitor names and ids
                # to help auto generate dashboards.  So, we want a monitor name like `docker_monitor(foo_container)`
                # for each running container.
                self._logger.emit_value(
                    key, metrics[value], extra, monitor_id_override=monitor_override
                )

    def __log_network_interface_metrics(
        self, container, metrics, interface=None, k8s_extra={}
    ):
        """ Logs network interface metrics

            @param container:  name of the container the log originated from
            @param metrics: a dict of metrics keys/values to emit
            @param interface: an optional interface value to associate with each metric value emitted
            @param k8s_extra: extra k8s specific key/value pairs to associate with each metric value emitted
        """
        extra = None
        if interface:
            if k8s_extra is None:
                extra = {}
            else:
                extra = k8s_extra.copy()

            extra["interface"] = interface

        self.__log_metrics(container, self.__network_metrics, metrics, extra)

    def __log_memory_stats_metrics(self, container, metrics, k8s_extra):
        """ Logs memory stats metrics

            @param container: name of the container the log originated from
            @param metrics: a dict of metrics keys/values to emit
            @param k8s_extra: extra k8s specific key/value pairs to associate with each metric value emitted
        """
        if "stats" in metrics:
            self.__log_metrics(
                container, self.__mem_stat_metrics, metrics["stats"], k8s_extra
            )

        self.__log_metrics(container, self.__mem_metrics, metrics, k8s_extra)

    def __log_cpu_stats_metrics(self, container, metrics, k8s_extra):
        """ Logs cpu stats metrics

            @param container: name of the container the log originated from
            @param metrics: a dict of metrics keys/values to emit
            @param k8s_extra: extra k8s specific key/value pairs to associate with each metric value emitted
        """
        if "cpu_usage" in metrics:
            cpu_usage = metrics["cpu_usage"]
            if self.__percpu_metrics and "percpu_usage" in cpu_usage:
                percpu = cpu_usage["percpu_usage"]
                count = 1
                if percpu:
                    for usage in percpu:
                        extra = {"cpu": count}
                        if k8s_extra is not None:
                            extra.update(k8s_extra)
                        self._logger.emit_value(
                            "docker.cpu.usage",
                            usage,
                            extra,
                            monitor_id_override=container,
                        )
                        count += 1
            self.__log_metrics(
                container, self.__cpu_usage_metrics, cpu_usage, k8s_extra
            )

        if "system_cpu_usage" in metrics:
            self._logger.emit_value(
                "docker.cpu.system_cpu_usage",
                metrics["system_cpu_usage"],
                k8s_extra,
                monitor_id_override=container,
            )

        if "throttling_data" in metrics:
            self.__log_metrics(
                container,
                self.__cpu_throttling_metrics,
                metrics["throttling_data"],
                k8s_extra,
            )

    def __log_json_metrics(self, container, metrics, k8s_extra):
        """ Log docker metrics based on the JSON response returned from querying the Docker API

            @param container: name of the container the log originated from
            @param metrics: a dict of metrics keys/values to emit
            @param k8s_extra: extra k8s specific key/value pairs to associate with each metric value emitted
        """
        for key, value in six.iteritems(metrics):
            if value is None:
                continue

            if key == "networks":
                for interface, network_metrics in six.iteritems(value):
                    self.__log_network_interface_metrics(
                        container, network_metrics, interface, k8s_extra=k8s_extra
                    )
            elif key == "network":
                self.__log_network_interface_metrics(container, value, k8s_extra)
            elif key == "memory_stats":
                self.__log_memory_stats_metrics(container, value, k8s_extra)
            elif key == "cpu_stats":
                self.__log_cpu_stats_metrics(container, value, k8s_extra)

    def __gather_metrics_from_api_for_container(self, container, k8s_extra):
        """ Query the Docker API for container metrics

            @param container: name of the container to query
            @param k8s_extra: extra k8s specific key/value pairs to associate with each metric value emitted
        """
        result = self.__metric_fetcher.get_metrics(container)
        if result is not None:
            self.__log_json_metrics(container, result, k8s_extra)

    def __build_k8s_controller_info(self, pod):
        """
            Builds a dict containing information about the controller settings for a given pod

            @param pod: a PodInfo object containing basic information (namespace/name) about the pod to query

            @return: a dict containing the controller name for the controller running
                     the specified pod, or an empty dict if the pod is not part of a controller
        """
        k8s_extra = {}
        if pod is not None:

            # default key and controller name
            key = "k8s-controller"
            name = "none"

            # check if we have a controller, and if so use it
            controller = pod.controller
            if controller is not None:

                # use one of the predefined key if this is a controller kind we know about
                if controller.kind in _CONTROLLER_KEYS:
                    key = _CONTROLLER_KEYS[controller.kind]

                name = controller.name

            k8s_extra = {key: name}
        return k8s_extra

    def __get_k8s_controller_info(self, container):
        """
            Gets information about the kubernetes controller of a given container
            @param container: a dict containing information about a container, returned by _get_containers
        """
        k8s_info = container.get("k8s_info", {})
        pod = k8s_info.get("pod_info", None)
        if pod is None:
            return None
        return self.__build_k8s_controller_info(pod)

    def __get_cluster_info(self, cluster_name):
        """ returns a dict of values about the cluster """
        cluster_info = {}
        if self.__include_controller_info and cluster_name is not None:
            cluster_info["k8s-cluster"] = cluster_name

        return cluster_info

    def __gather_metrics_from_api(self, containers, cluster_name):

        cluster_info = self.__get_cluster_info(cluster_name)

        for cid, info in six.iteritems(containers):
            self.__metric_fetcher.prefetch_metrics(info["name"])

        for cid, info in six.iteritems(containers):
            k8s_extra = {}
            if self.__include_controller_info:
                k8s_extra = self.__get_k8s_controller_info(info)
                if k8s_extra is not None:
                    k8s_extra.update(cluster_info)
                    k8s_extra.update({"pod_uid": info["name"]})
                else:
                    k8s_extra = {}
            self.__gather_metrics_from_api_for_container(info["name"], k8s_extra)

    def __gather_k8s_metrics_for_node(self, node, extra):
        """
            Gathers metrics from a Kubelet API response for a specific pod

            @param node_metrics: A JSON Object from a response to a Kubelet API query
            @param extra: Extra fields to append to each metric
        """

        name = node.get("nodeName", None)
        if name is None:
            return

        node_extra = {"node_name": name}
        node_extra.update(extra)

        for key, metrics in six.iteritems(node):
            if key == "network":
                self.__log_metrics(
                    name, self.__k8s_node_network_metrics, metrics, node_extra
                )

    def __gather_k8s_metrics_for_pod(self, pod_metrics, pod_info, k8s_extra):
        """
            Gathers metrics from a Kubelet API response for a specific pod

            @param pod_metrics: A JSON Object from a response to a Kubelet API query
            @param pod_info: A PodInfo structure regarding the pod in question
            @param k8s_extra: Extra k8s specific fields to append to each metric
        """

        extra = {"pod_uid": pod_info.uid}

        extra.update(k8s_extra)

        for key, metrics in six.iteritems(pod_metrics):
            if key == "network":
                self.__log_metrics(
                    pod_info.uid, self.__k8s_pod_network_metrics, metrics, extra
                )

    def __gather_k8s_metrics_from_kubelet(self, containers, kubelet_api, cluster_name):
        """
            Gathers k8s metrics from a response to a stats query of the Kubelet API

            @param containers: a dict returned by _get_containers with info for all containers we are interested in
            @param kubelet_api: a KubeletApi object for querying the KubeletApi
            @param cluster_name: the name of the k8s cluster

        """

        cluster_info = self.__get_cluster_info(cluster_name)

        # get set of pods we are interested in querying
        pod_info = {}
        for cid, info in six.iteritems(containers):
            k8s_info = info.get("k8s_info", {})
            pod = k8s_info.get("pod_info", None)
            if pod is None:
                continue

            pod_info[pod.uid] = pod

        try:
            stats = kubelet_api.query_stats()
            node = stats.get("node", {})

            if node:
                self.__gather_k8s_metrics_for_node(node, cluster_info)

            pods = stats.get("pods", [])

            # process pod stats, skipping any that are not in our list
            # of pod_info
            for pod in pods:
                pod_ref = pod.get("podRef", {})
                pod_uid = pod_ref.get("uid", "<invalid>")
                if pod_uid not in pod_info:
                    continue

                info = pod_info[pod_uid]
                controller_info = {}
                if self.__include_controller_info:
                    controller_info = self.__build_k8s_controller_info(info)
                    controller_info.update(cluster_info)
                self.__gather_k8s_metrics_for_pod(pod, info, controller_info)

        except ConnectionError as e:
            self._logger.warning(
                "Error connecting to kubelet API: %s.  No Kubernetes stats will be available"
                % six.text_type(e),
                limit_once_per_x_secs=3600,
                limit_key="kubelet-api-connection-stats",
            )
        except KubeletApiException as e:
            self._logger.warning(
                "Error querying kubelet API: %s" % six.text_type(e),
                limit_once_per_x_secs=300,
                limit_key="kubelet-api-query-stats",
            )

    def __get_k8s_cache(self):
        k8s_cache = None
        if self.__container_checker:
            k8s_cache = self.__container_checker.k8s_cache
        return k8s_cache

    def get_extra_server_attributes(self):
        # Immutable, hence thread safe
        return {"_k8s_ver": "star"}

    def get_user_agent_fragment(self):
        """This method is periodically invoked by a separate (MonitorsManager) thread and must be thread safe."""
        k8s_cache = self.__get_k8s_cache()
        ver = None
        runtime = None
        if k8s_cache:
            ver = k8s_cache.get_api_server_version()
            runtime = k8s_cache.get_container_runtime()
        ver = "k8s=%s" % (ver if ver else "true")
        if runtime:
            ver += ";k8s-runtime=%s" % runtime

        return ver

    def gather_sample(self):
        k8s_cache = self.__get_k8s_cache()

        cluster_name = None
        if k8s_cache is not None:
            cluster_name = k8s_cache.get_cluster_name()

        # gather metrics
        containers = None
        if self.__report_container_metrics and self.__client:
            if (
                self.__metrics_controlled_warmer is not None
                and not self.__metrics_controlled_warmer.is_running()
            ):
                self.__metrics_controlled_warmer.set_k8s_cache(k8s_cache)
                self.__metrics_controlled_warmer.start()
            containers = _get_containers(
                self.__client,
                ignore_container=None,
                glob_list=self.__glob_list,
                k8s_cache=k8s_cache,
                k8s_include_by_default=self.__include_all,
                k8s_namespaces_to_include=self.__namespaces_to_include,
                controlled_warmer=self.__metrics_controlled_warmer,
            )
        try:
            if containers:
                if self.__report_container_metrics:
                    self._logger.log(
                        scalyr_logging.DEBUG_LEVEL_3,
                        "Attempting to retrieve metrics for %d containers"
                        % len(containers),
                    )
                    self.__gather_metrics_from_api(containers, cluster_name)

                if self.__report_k8s_metrics:
                    self._logger.log(
                        scalyr_logging.DEBUG_LEVEL_3,
                        "Attempting to retrieve k8s metrics %d" % len(containers),
                    )
                    self.__gather_k8s_metrics_from_kubelet(
                        containers, self.__kubelet_api, cluster_name
                    )
        except Exception as e:
            self._logger.exception(
                "Unexpected error logging metrics: %s" % (six.text_type(e))
            )

        if self.__gather_k8s_pod_info:
            cluster_info = self.__get_cluster_info(cluster_name)

            containers = self._container_enumerator.get_containers(  # pylint: disable=no-member
                k8s_cache=k8s_cache,
                k8s_include_by_default=self.__include_all,
                k8s_namespaces_to_include=self.__namespaces_to_include,
            )
            for cid, info in six.iteritems(containers):
                try:
                    extra = info.get("k8s_info", {})
                    extra["status"] = info.get("status", "unknown")
                    if self.__include_controller_info:
                        controller = self.__get_k8s_controller_info(info)
                        extra.update(controller)
                        extra.update(cluster_info)

                    namespace = extra.get("pod_namespace", "invalid-namespace")
                    self._logger.emit_value(
                        "%s.container_name"
                        % (self._container_runtime),  # pylint: disable=no-member
                        info["name"],
                        extra,
                        monitor_id_override="namespace:%s" % namespace,
                    )
                except Exception as e:
                    self._logger.error(
                        "Error logging container information for %s: %s"
                        % (_get_short_cid(cid), six.text_type(e))
                    )

            if self.__container_checker:
                namespaces = self.__container_checker.get_k8s_data()
                for namespace, pods in six.iteritems(namespaces):
                    for pod_name, pod in six.iteritems(pods):
                        try:
                            extra = {
                                "pod_uid": pod.uid,
                                "pod_namespace": pod.namespace,
                                "node_name": pod.node_name,
                            }

                            if self.__include_controller_info:
                                controller_info = self.__build_k8s_controller_info(pod)
                                if controller_info:
                                    extra.update(controller_info)
                                extra.update(cluster_info)

                            self._logger.emit_value(
                                "k8s.pod",
                                pod.name,
                                extra,
                                monitor_id_override="namespace:%s" % pod.namespace,
                            )
                        except Exception as e:
                            self._logger.error(
                                "Error logging pod information for %s: %s"
                                % (pod.name, six.text_type(e))
                            )

    def run(self):
        # workaround a multithread initialization problem with time.strptime
        # see: http://code-trick.com/python-bug-attribute-error-_strptime/
        # we can ignore the result
        time.strptime("2016-08-29", "%Y-%m-%d")

        if self.__container_checker:
            self.__container_checker.start()

        k8s_cache = self.__get_k8s_cache()

        envars_to_log = [
            "SCALYR_K8S_NODE_NAME",
            "SCALYR_K8S_POD_NAME",
            "SCALYR_K8S_POD_NAMESPACE",
            "SCALYR_K8S_POD_UID",
            "SCALYR_K8S_KUBELET_HOST_IP",
            "SCALYR_K8S_CLUSTER_NAME",
            "SCALYR_K8S_DISABLE_API_SERVER",
            "SCALYR_K8S_CACHE_EXPIRY_SECS",
            "SCALYR_K8S_CACHE_PURGE_SECS",
            "SCALYR_K8S_CACHE_START_FUZZ_SECS",
            "SCALYR_K8S_CACHE_EXPIRY_FUZZ_SECS",
            "SCALYR_COMPRESSION_TYPE",
            "SCALYR_ENABLE_PROFILING",
            "SCALYR_PROFILE_DURATION_MINUTES",
            "SCALYR_MAX_PROFILE_INTERVAL_MINUTES",
            "SCALYR_K8S_ALWAYS_USE_DOCKER",
            "SCALYR_K8S_CACHE_BATCH_POD_UPDATES",
            "SCALYR_K8S_CACHE_DISABLE_NODE_FILTER",
            "SCALYR_K8S_CONTROLLED_WARMER_MAX_ATTEMPTS",
            "SCALYR_K8S_CONTROLLED_WARMER_MAX_QUERY_RETRIES",
            "SCALYR_K8S_CONTROLLED_WARMER_BLACKLIST_TIME",
            "SCALYR_K8S_RATELIMIT_CLUSTER_NUM_AGENTS",
            "SCALYR_K8S_RATELIMIT_CLUSTER_RPS_INIT",
            "SCALYR_K8S_RATELIMIT_CLUSTER_RPS_MIN",
            "SCALYR_K8S_RATELIMIT_CLUSTER_RPS_MAX",
            "SCALYR_K8S_RATELIMIT_CONSECUTIVE_INCREASE_THRESHOLD",
            "SCALYR_K8S_RATELIMIT_INCREASE_STRATEGY",
            "SCALYR_K8S_RATELIMIT_INCREASE_FACTOR",
            "SCALYR_K8S_RATELIMIT_BACKOFF_FACTOR",
            "SCALYR_K8S_RATELIMIT_MAX_CONCURRENCY",
            "SCALYR_K8S_SIDECAR_MODE",
            "SCALYR_K8S_KUBELET_API_URL_TEMPLATE",
            "SCALYR_K8S_VERIFY_KUBELET_QUERIES",
            "SCALYR_K8S_KUBELET_CA_CERT",
        ]
        for envar in envars_to_log:
            self._logger.info(
                "Environment variable %s : %s"
                % (envar, compat.os_environ_unicode.get(envar, "<Not set>"))
            )

        try:
            # check to see if the user has manually specified a cluster name, and if so then
            # force enable 'Starbuck' features
            if (
                self.__container_checker
                and self.__container_checker.get_cluster_name(
                    self.__container_checker.k8s_cache
                )
                is not None
            ):
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Cluster name detected, enabling k8s metric reporting and controller information",
                )
                self.__include_controller_info = True
                self.__report_k8s_metrics = self.__report_container_metrics

            if self.__report_k8s_metrics:

                runtime = None
                if k8s_cache:
                    # TODO(czerwin):  If the api server has been disabled, we need to decide what to do here.
                    runtime = k8s_cache.get_container_runtime()

                if runtime == "docker":
                    self.__client = DockerClient(
                        base_url=("unix:/%s" % self.__socket_file),
                        version=self.__docker_api_version,
                    )
                    self.__metric_fetcher = DockerMetricFetcher(
                        self.__client, self.__docker_max_parallel_stats
                    )

                k8s = KubernetesApi.create_instance(
                    self._global_config, k8s_api_url=self.__k8s_api_url
                )
                self.__kubelet_api = KubeletApi(
                    k8s,
                    node_name=compat.os_environ_unicode.get(
                        "SCALYR_K8S_NODE_NAME", None
                    ),
                    host_ip=self._config.get("k8s_kubelet_host_ip"),
                    kubelet_url_template=Template(
                        self._config.get("k8s_kubelet_api_url_template")
                    ),
                    ca_file=self._global_config.k8s_kubelet_ca_cert,
                    verify_https=self._global_config.k8s_verify_kubelet_queries,
                )
        except Exception as e:
            self._logger.error(
                "Error creating KubeletApi object. Kubernetes metrics will not be logged: %s"
                % six.text_type(e)
            )
            self.__report_k8s_metrics = False

        global_log.info(
            "kubernetes_monitor parameters: ignoring namespaces: %s, report_controllers: %s, report_metrics: %s"
            % (
                self.__namespaces_to_include,
                self.__include_controller_info,
                self.__report_container_metrics,
            )
        )

        server = scalyr_util.get_web_url_from_upload_url(
            self._global_config.scalyr_server
        )
        global_log.info(
            "View the log for this agent at: %s/events?filter=$serverHost%%3D%%27%s%%27&log=%%2Fvar%%2Flog%%2Fscalyr-agent-2%%2Fagent.log"
            % (server, quote_plus(self._global_config.server_attributes["serverHost"])),
            force_stdout=True,
        )

        ScalyrMonitor.run(self)

    def stop(self, wait_on_join=True, join_timeout=5):
        if (
            self.__metrics_controlled_warmer is not None
            and self.__metrics_controlled_warmer.is_running()
        ):
            self.__metrics_controlled_warmer.stop(
                wait_on_join=wait_on_join, join_timeout=join_timeout
            )

        # stop the main server
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)

        if self.__container_checker is not None:
            self.__container_checker.stop(wait_on_join, join_timeout)

        if self.__metric_fetcher is not None:
            self.__metric_fetcher.stop()
