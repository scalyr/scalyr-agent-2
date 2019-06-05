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

__author__ = 'imron@scalyr.com'

import datetime
import docker
import fnmatch
import glob
import traceback
import os
import re
import stat
from string import Template
import time
from scalyr_agent import ScalyrMonitor, define_config_option, define_metric
import scalyr_agent.util as scalyr_util
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import JsonObject, ArrayOfStrings
from scalyr_agent.monitor_utils.k8s import KubernetesApi, KubeletApi, KubeletApiException, DockerMetricFetcher
import scalyr_agent.monitor_utils.k8s as k8s_utils
from scalyr_agent.third_party.requests.exceptions import ConnectionError

from scalyr_agent.util import StoppableThread


global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.kubernetes_monitor``',
                     convert_to=str, required_option=True)

define_config_option( __monitor__, 'container_name',
                     'Optional (defaults to None). Defines a regular expression that matches the name given to the '
                     'container running the scalyr-agent.\n'
                     'If this is None, the scalyr agent will look for a container running /usr/sbin/scalyr-agent-2 as the main process.\n',
                     convert_to=str, default=None)

define_config_option( __monitor__, 'container_check_interval',
                     'Optional (defaults to 5). How often (in seconds) to check if containers have been started or stopped.',
                     convert_to=int, default=5, env_aware=True)

define_config_option( __monitor__, 'api_socket',
                     'Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket used to communicate with '
                     'the docker API.   WARNING, if you have `mode` set to `syslog`, you must also set the '
                     '`docker_api_socket` configuration option in the syslog monitor to this same value\n'
                     'Note:  You need to map the host\'s /run/docker.sock to the same value as specified here, using the -v parameter, e.g.\n'
                     '\tdocker run -v /run/docker.sock:/var/scalyr/docker.sock ...',
                     convert_to=str, default='/var/scalyr/docker.sock')

define_config_option( __monitor__, 'docker_api_version',
                     'Optional (defaults to \'auto\'). The version of the Docker API to use.  WARNING, if you have '
                     '`mode` set to `syslog`, you must also set the `docker_api_version` configuration option in the '
                     'syslog monitor to this same value\n',
                     convert_to=str, default='auto')

define_config_option( __monitor__, 'docker_log_prefix',
                     'Optional (defaults to docker). Prefix added to the start of all docker logs. ',
                     convert_to=str, default='docker')

define_config_option( __monitor__, 'docker_max_parallel_stats',
                     'Optional (defaults to 20). Maximum stats requests to issue in parallel when retrieving container '
                     'metrics using the Docker API.', convert_to=int, default=20, env_aware=True)

define_config_option( __monitor__, 'max_previous_lines',
                     'Optional (defaults to 5000). The maximum number of lines to read backwards from the end of the stdout/stderr logs\n'
                     'when starting to log a containers stdout/stderr to find the last line that was sent to Scalyr.',
                     convert_to=int, default=5000)

define_config_option( __monitor__, 'readback_buffer_size',
                     'Optional (defaults to 5k). The maximum number of bytes to read backwards from the end of any log files on disk\n'
                     'when starting to log a containers stdout/stderr.  This is used to find the most recent timestamp logged to file '
                     'was sent to Scalyr.',
                     convert_to=int, default=5*1024)

define_config_option( __monitor__, 'log_mode',
                     'Optional (defaults to "docker_api"). Determine which method is used to gather logs from the '
                     'local containers. If "docker_api", then this agent will use the docker API to contact the local '
                     'containers and pull logs from them.  If "syslog", then this agent expects the other containers '
                     'to push logs to this one using the syslog Docker log plugin.  Currently, "syslog" is the '
                     'preferred method due to bugs/issues found with the docker API.  It is not the default to protect '
                     'legacy behavior.\n',
                     convert_to=str, default="docker_api")

define_config_option( __monitor__, 'container_globs',
                     'Optional (defaults to None). If true, a list of glob patterns for container names.  Only containers whose names '
                     'match one of the glob patterns will be monitored.',
                      convert_to=ArrayOfStrings, default=None, env_aware=True)

define_config_option( __monitor__, 'report_container_metrics',
                      'Optional (defaults to True). If true, metrics will be collected from the container and reported  '
                      'to Scalyr.  Note, metrics are only collected from those containers whose logs are being collected',
                      convert_to=bool, default=True, env_aware=True)

define_config_option( __monitor__, 'report_k8s_metrics',
                      'Optional (defaults to True). If true and report_container_metrics is true, metrics will be '
                      'collected from the k8s and reported to Scalyr.  ', convert_to=bool, default=False, env_aware=True)

define_config_option( __monitor__, 'k8s_ignore_namespaces',
                      'Optional (defaults to "kube-system"). A comma-delimited list of the namespaces whose pods\'s '
                      'logs should not be collected and sent to Scalyr.', convert_to=str, default="kube-system")

define_config_option( __monitor__, 'k8s_ignore_pod_sandboxes',
                      'Optional (defaults to True). If True then all containers with the label '
                      '`io.kubernetes.docker.type` equal to `podsandbox` are excluded from the'
                      'logs being collected', convert_to=bool, default=True, env_aware=True)

define_config_option( __monitor__, 'k8s_include_all_containers',
                      'Optional (defaults to True). If True, all containers in all pods will be monitored by the kubernetes monitor '
                      'unless they have an include: false or exclude: true annotation. '
                      'If false, only pods/containers with an include:true or exclude:false annotation '
                      'will be monitored. See documentation on annotations for further detail.', convert_to=bool, default=True, env_aware=True)

define_config_option( __monitor__, 'k8s_use_v2_attributes',
                      'Optional (defaults to False). If True, will use v2 version of attribute names instead of '
                      'the names used with the original release of this monitor.  This is a breaking change so could '
                      'break searches / alerts if you rely on the old names', convert_to=bool, default=False)

define_config_option( __monitor__, 'k8s_use_v1_and_v2_attributes',
                      'Optional (defaults to False). If True, send attributes using both v1 and v2 versions of their'
                      'names.  This may be used to fix breakages when you relied on the v1 attribute names',
                      convert_to=bool, default=False)

define_config_option( __monitor__, 'k8s_api_url',
                      'Optional (defaults to "https://kubernetes.default"). The URL for the Kubernetes API server for '
                      'this cluster.', convert_to=str, default='https://kubernetes.default')

define_config_option( __monitor__, 'k8s_cache_expiry_secs',
                     'Optional (defaults to 30). The amount of time to wait between fully updating the k8s cache from the k8s api. '
                     'Increase this value if you want less network traffic from querying the k8s api.  Decrease this value if you '
                     'want dynamic updates to annotation configuration values to be processed more quickly.',
                     convert_to=int, default=30)

define_config_option( __monitor__, 'k8s_cache_purge_secs',
                     'Optional (defaults to 300). The number of seconds to wait before purging unused items from the k8s cache',
                     convert_to=int, default=300)

define_config_option( __monitor__, 'k8s_cache_init_abort_delay',
                     'Optional (defaults to 20). The number of seconds to wait for initialization of the kubernetes cache before aborting '
                     'the kubernetes_monitor.',
                     convert_to=int, default=20)

define_config_option( __monitor__, 'k8s_parse_json',
                      'Deprecated, please use `k8s_parse_format`. If set, and True, then this flag will override the `k8s_parse_format` to `auto`. '
                      'If set and False, then this flag will override the `k8s_parse_format` to `raw`.',
                      convert_to=bool, default=None)

define_config_option( __monitor__, 'k8s_parse_format',
                      'Optional (defaults to `auto`). Valid values are: `auto`, `json`, `cri` and `raw`. '
                      'If `auto`, the monitor will try to detect the format of the raw log files, '
                      'e.g. `json` or `cri`.  Log files will be parsed in this format before uploading to the server '
                      'to extract log and timestamp fields.  If `raw`, the raw contents of the log will be uploaded to Scalyr. '
                      '(Note: An incorrect setting can cause parsing to fail which will result in raw logs being uploaded to Scalyr, so please leave '
                      'this as `auto` if in doubt.)',
                      convert_to=str, default='auto', env_aware=True)

define_config_option( __monitor__, 'k8s_always_use_cri',
                     'Optional (defaults to False). If True, the kubernetes monitor will always try to read logs using the container runtime interface '
                     'even when the runtime is detected as docker',
                     convert_to=bool, default=False, env_aware=True)

define_config_option( __monitor__, 'k8s_cri_query_filesystem',
                     'Optional (defaults to False). If True, then when in CRI mode, the monitor will only query the filesystem for the list of active containers, rather than first querying the Kubelet API. This is a useful optimization when the Kubelet API is known to be disabled.',
                     convert_to=bool, default=False, env_aware=True)

define_config_option( __monitor__, 'k8s_verify_api_queries',
                      'Optional (defaults to True). If true, then the ssl connection for all queries to the k8s API will be verified using '
                      'the ca.crt certificate found in the service account directory. If false, no verification will be performed. '
                      'This is useful for older k8s clusters where certificate verification can fail.',
                      convert_to=bool, default=True)

define_config_option( __monitor__, 'gather_k8s_pod_info',
                      'Optional (defaults to False). If true, then every gather_sample interval, metrics will be collected '
                      'from the docker and k8s APIs showing all discovered containers and pods. This is mostly a debugging aid '
                      'and there are performance implications to always leaving this enabled', convert_to=bool, default=False, env_aware=True)

define_config_option( __monitor__, 'include_daemonsets_as_deployments',
                      'Deprecated',
                      convert_to=bool, default=True)

# for now, always log timestamps to help prevent a race condition
#define_config_option( __monitor__, 'log_timestamps',
#                     'Optional (defaults to False). If true, stdout/stderr logs will contain docker timestamps at the beginning of the line\n',
#                     convert_to=bool, default=False)

define_metric( __monitor__, "docker.net.rx_bytes", "Total received bytes on the network interface", cumulative=True, unit="bytes", category="Network" )
define_metric( __monitor__, "docker.net.rx_dropped", "Total receive packets dropped on the network interface", cumulative=True, category="Network" )
define_metric( __monitor__, "docker.net.rx_errors", "Total receive errors on the network interface", cumulative=True, category="Network" )
define_metric( __monitor__, "docker.net.rx_packets", "Total received packets on the network interface", cumulative=True, category="Network" )
define_metric( __monitor__, "docker.net.tx_bytes", "Total transmitted bytes on the network interface", cumulative=True, unit="bytes", category="Network" )
define_metric( __monitor__, "docker.net.tx_dropped", "Total transmitted packets dropped on the network interface", cumulative=True, category="Network" )
define_metric( __monitor__, "docker.net.tx_errors", "Total transmission errors on the network interface", cumulative=True, category="Network" )
define_metric( __monitor__, "docker.net.tx_packets", "Total packets transmitted on the network intervace", cumulative=True, category="Network" )

define_metric( __monitor__, "docker.mem.stat.active_anon", "The number of bytes of active memory backed by anonymous pages, excluding sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.active_file", "The number of bytes of active memory backed by files, excluding sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.cache", "The number of bytes used for the cache, excluding sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.hierarchical_memory_limit", "The memory limit in bytes for the container.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.inactive_anon", "The number of bytes of inactive memory in anonymous pages, excluding sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.inactive_file", "The number of bytes of inactive memory in file pages, excluding sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.mapped_file", "The number of bytes of mapped files, excluding sub-groups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.pgfault", "The total number of page faults, excluding sub-cgroups.", cumulative=True, category="Memory" )
define_metric( __monitor__, "docker.mem.stat.pgmajfault", "The number of major page faults, excluding sub-cgroups", cumulative=True, category="Memory" )
define_metric( __monitor__, "docker.mem.stat.pgpgin", "The number of charging events, excluding sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.pgpgout", "The number of uncharging events, excluding sub-groups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.rss", "The number of bytes of anonymous and swap cache memory (includes transparent hugepages), excluding sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.rss_huge", "The number of bytes of anonymous transparent hugepages, excluding sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.unevictable", "The number of bytes of memory that cannot be reclaimed (mlocked etc), excluding sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.writeback", "The number of bytes being written back to disk, excluding sub-cgroups", category="Memory" )

define_metric( __monitor__, "docker.mem.stat.total_active_anon", "The number of bytes of active memory backed by anonymous pages, including sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_active_file", "The number of bytes of active memory backed by files, including sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_cache", "The number of bytes used for the cache, including sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_inactive_anon", "The number of bytes of inactive memory in anonymous pages, including sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_inactive_file", "The number of bytes of inactive memory in file pages, including sub-cgroups.", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_mapped_file", "The number of bytes of mapped files, including sub-groups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_pgfault", "The total number of page faults, including sub-cgroups.", cumulative=True, category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_pgmajfault","The number of major page faults, including sub-cgroups", cumulative=True, category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_pgpgin", "The number of charging events, including sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_pgpgout", "The number of uncharging events, including sub-groups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_rss", "The number of bytes of anonymous and swap cache memory (includes transparent hugepages), including sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_rss_huge", "The number of bytes of anonymous transparent hugepages, including sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_unevictable", "The number of bytes of memory that cannot be reclaimed (mlocked etc), including sub-cgroups", category="Memory" )
define_metric( __monitor__, "docker.mem.stat.total_writeback",  "The number of bytes being written back to disk, including sub-cgroups", category="Memory" )



define_metric( __monitor__, "docker.mem.max_usage", "The max amount of memory used by container in bytes.", unit="bytes", category="Memory"  )
define_metric( __monitor__, "docker.mem.usage", "The current number of bytes used for memory including cache.", unit="bytes", category="Memory"  )
define_metric( __monitor__, "docker.mem.fail_cnt", "The number of times the container hit its memory limit", category="Memory" )
define_metric( __monitor__, "docker.mem.limit", "The memory limit for the container in bytes.", unit="bytes", category="Memory")

define_metric( __monitor__, "docker.cpu.usage", "Total CPU consumed by container in nanoseconds", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.system_cpu_usage", "Total CPU consumed by container in kernel mode in nanoseconds", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.usage_in_usermode", "Total CPU consumed by tasks of the cgroup in user mode in nanoseconds", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.total_usage", "Total CPU consumed by tasks of the cgroup in nanoseconds", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.usage_in_kernelmode", "Total CPU consumed by tasks of the cgroup in kernel mode in nanoseconds", cumulative=True, category="CPU" )

define_metric( __monitor__, "docker.cpu.throttling.periods", "The number of of periods with throttling active.", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.throttling.throttled_periods", "The number of periods where the container hit its throttling limit", cumulative=True, category="CPU" )
define_metric( __monitor__, "docker.cpu.throttling.throttled_time", "The aggregate amount of time the container was throttled in nanoseconds", cumulative=True, category="CPU" )

define_metric( __monitor__, "k8s.pod.network.rx_bytes", "The total received bytes on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.pod.network.rx_errors", "The total received errors on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.pod.network.tx_bytes", "The total transmitted bytes on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.pod.network.tx_errors", "The total transmission errors on a pod", cumulative=True, category="Network" )

define_metric( __monitor__, "k8s.node.network.rx_bytes", "The total received bytes on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.node.network.rx_errors", "The total received errors on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.node.network.tx_bytes", "The total transmitted bytes on a pod", cumulative=True, category="Network" )
define_metric( __monitor__, "k8s.node.network.tx_errors", "The total transmission errors on a pod", cumulative=True, category="Network" )

# A mapping of k8s controller kinds to the appropriate field name
# passed to the scalyr server for metrics that originate from pods
# controlled by that object. See #API-62
_CONTROLLER_KEYS = {
    'CronJob' : 'k8s-cron-job',
    'DaemonSet' : 'k8s-daemon-set',
    'Deployment' : 'k8s-deployment',
    'Job' : 'k8s-job',
    'ReplicaSet': 'k8s-replica-set',
    'ReplicationController': 'k8s-replication-controller',
    'StatefulSet': 'k8s-stateful-set'
}

# A regex for splitting a container id and runtime
_CID_RE = re.compile( '^(.+)://(.+)$' )

class K8sInitException( Exception ):
    """ Wrapper exception to indicate when the monitor failed to start due to
        a problem with initializing the k8s cache
    """

class WrappedStreamResponse( object ):
    """ Wrapper for generator returned by docker.Client._stream_helper
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """
    def __init__( self, client, response, decode ):
        self.client = client
        self.response = response
        self.decode = self.decode

    def __iter__( self ):
        for item in super( DockerClient, self.client )._stream_helper( self.response, self.decode ):
            yield item

class WrappedRawResponse( object ):
    """ Wrapper for generator returned by docker.Client._stream_raw_result
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """
    def __init__( self, client, response ):
        self.client = client
        self.response = response

    def __iter__( self ):
        for item in super( DockerClient, self.client )._stream_raw_result( self.response ):
            yield item

class WrappedMultiplexedStreamResponse( object ):
    """ Wrapper for generator returned by docker.Client._multiplexed_response_stream_helper
        that gives us access to the response, and therefore the socket, so that
        we can shutdown the socket from another thread if needed
    """
    def __init__( self, client, response ):
        self.client = client
        self.response = response

    def __iter__( self ):
        for item in super( DockerClient, self.client )._multiplexed_response_stream_helper( self.response ):
            yield item

class DockerClient( docker.Client ):
    """ Wrapper for docker.Client to return 'wrapped' versions of streamed responses
        so that we can have access to the response object, which allows us to get the
        socket in use, and shutdown the blocked socket from another thread (e.g. upon
        shutdown
    """
    def _stream_helper( self, response, decode=False ):
        return WrappedStreamResponse( self, response, decode )

    def _stream_raw_result( self, response ):
        return WrappedRawResponse( self, response )

    def _multiplexed_response_stream_helper( self, response ):
        return WrappedMultiplexedStreamResponse( self, response )

    def _get_raw_response_socket(self, response):
        if response.raw._fp.fp:
            return super( DockerClient, self )._get_raw_response_socket( response )

        return None

def _split_datetime_from_line( line ):
    """Docker timestamps are in RFC3339 format: 2015-08-03T09:12:43.143757463Z, with everything up to the first space
    being the timestamp.
    """
    log_line = line
    dt = datetime.datetime.utcnow()
    pos = line.find( ' ' )
    if pos > 0:
        dt = scalyr_util.rfc3339_to_datetime( line[0:pos] )
        log_line = line[pos+1:]

    return (dt, log_line)

def _get_short_cid( container_id ):
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

def _ignore_old_dead_container( container, created_before=None ):
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
        state = container.get( 'State', {} )

        #ignore any that are finished and that are also too old
        if state != 'running':
            created = container.get( 'Created', 0 ) # default to a long time ago
            if created < created_before:
                return True

    return False

def _get_containers(client, ignore_container=None, restrict_to_container=None, logger=None,
                    only_running_containers=True, running_or_created_after=None, glob_list=None, include_log_path=False, k8s_cache=None,
                    k8s_include_by_default=True, k8s_namespaces_to_exclude=None, ignore_pod_sandboxes=True, current_time=None):
    """Queries the Docker API and returns a dict of running containers that maps container id to container name, and other info
        @param client: A docker.Client object
        @param ignore_container: String, a single container id to exclude from the results (useful for ignoring the scalyr_agent container)
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
        @param k8s_namespaces_to_exclude: List  The of namespaces whose containers should be excluded.
        @param ignore_pod_sandboxes: Boolean.  If True then any k8s pod sandbox containers are ignored from the list of monitored containers
        @param current_time.  Timestamp since the epoch
    """
    if logger is None:
        logger = global_log

    k8s_labels = {
        'pod_uid': 'io.kubernetes.pod.uid',
        'pod_name': 'io.kubernetes.pod.name',
        'pod_namespace': 'io.kubernetes.pod.namespace',
        'k8s_container_name': 'io.kubernetes.container.name'
    }

    if running_or_created_after is not None:
        only_running_containers=False

    result = {}
    try:
        filters = {"id": restrict_to_container} if restrict_to_container is not None else None
        response = client.containers(filters=filters, all=not only_running_containers)
        for container in response:
            cid = container['Id']
            short_cid = _get_short_cid( cid )

            if ignore_container is not None and cid == ignore_container:
                continue

            # Note we need to *include* results that were created after the 'running_or_created_after' time.
            # that means we need to *ignore* any containers created before that
            # hence the reason 'create_before' is assigned to a value named '...created_after'
            if _ignore_old_dead_container( container, created_before=running_or_created_after ):
                continue

            if len( container['Names'] ) > 0:
                name = container['Names'][0].lstrip('/')

                # ignore any pod sandbox containers
                if ignore_pod_sandboxes:
                    container_type = container.get( 'Labels', {} ).get( 'io.kubernetes.docker.type', '' )
                    if container_type == 'podsandbox':
                        continue

                add_container = True

                if glob_list:
                    add_container = False
                    for glob in glob_list:
                        if fnmatch.fnmatch( name, glob ):
                            add_container = True
                            break

                if add_container:
                    log_path = None
                    k8s_info = None
                    status = None
                    if include_log_path or k8s_cache is not None:
                        try:
                            info = client.inspect_container( cid )

                            log_path = info['LogPath'] if include_log_path and 'LogPath' in info else None

                            if not only_running_containers:
                                status = info['State']['Status']

                            if k8s_cache is not None:
                                config = info.get('Config', {} )
                                labels = config.get( 'Labels', {} )

                                k8s_info = {}
                                missing_field = False

                                for key, label in k8s_labels.iteritems():
                                    value = labels.get( label )
                                    if value:
                                        k8s_info[key] = value
                                    else:
                                        missing_field = True
                                        logger.warn( "Missing kubernetes label '%s' in container %s" % (label, short_cid), limit_once_per_x_secs=300,limit_key="docker-inspect-k8s-%s" % short_cid)

                                if missing_field:
                                    logger.log( scalyr_logging.DEBUG_LEVEL_1, "Container Labels %s" % (scalyr_util.json_encode(labels)), limit_once_per_x_secs=300,limit_key="docker-inspect-container-dump-%s" % short_cid)

                                if 'pod_name' in k8s_info and 'pod_namespace' in k8s_info:
                                    if k8s_namespaces_to_exclude is not None and k8s_info['pod_namespace'] in k8s_namespaces_to_exclude:
                                        logger.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' based excluded namespaces" % short_cid)
                                        continue

                                    pod = k8s_cache.pod( k8s_info['pod_namespace'], k8s_info['pod_name'], current_time )
                                    if pod:
                                        k8s_info['pod_info'] = pod

                                        k8s_container = k8s_info.get( 'k8s_container_name', None )

                                        # check to see if we should exclude this container
                                        default_exclude = not k8s_include_by_default
                                        exclude = pod.exclude_pod( container_name=k8s_container, default=default_exclude)

                                        if exclude:
                                            if pod.annotations:
                                                logger.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' based on pod annotations, %s" % (short_cid, str(pod.annotations)) )
                                            continue

                                        # add a debug message if containers are excluded by default but this container is included
                                        if default_exclude and not exclude:
                                            logger.log( scalyr_logging.DEBUG_LEVEL_2, "Including container '%s' based on pod annotations, %s" % (short_cid, str(pod.annotations)) )

                        except Exception, e:
                          logger.error("Error inspecting container '%s' - %s, %s" % (cid, e, traceback.format_exc()), limit_once_per_x_secs=300,limit_key="docker-api-inspect")


                    result[cid] = {'name': name, 'log_path': log_path }

                    if status:
                        result[cid]['status'] = status

                    if k8s_info:
                        result[cid]['k8s_info'] = k8s_info

            else:
                result[cid] = {'name': cid, 'log_path': None}

    except Exception, e:  # container querying failed
        logger.error("Error querying running containers", limit_once_per_x_secs=300,
                     limit_key='docker-api-running-containers' )
        result = None

    return result

class ContainerEnumerator( object):
    """
    Base class that defines an api for enumerating all containers running on a node
    """

    def __init__( self, container_id ):
        self._container_id = container_id

    def get_containers( self, running_or_created_after=None, glob_list=None, k8s_cache=None, k8s_include_by_default=True, k8s_namespaces_to_exclude=None, current_time=None ):
        raise NotImplementedError()

class DockerEnumerator( ContainerEnumerator ):
    """
    Container Enumerator that retrieves the list of containers by querying the docker remote API over the docker socket by usin
    a docker.Client
    """
    def __init__( self, client, container_id ):
        super( DockerEnumerator, self).__init__( container_id )
        self._client = client

    def get_containers( self, running_or_created_after=None, glob_list=None, k8s_cache=None, k8s_include_by_default=True, k8s_namespaces_to_exclude=None, current_time=None ):
        return _get_containers(
            self._client,
            ignore_container=self._container_id,
            running_or_created_after=running_or_created_after,
            glob_list=glob_list,
            include_log_path=True,
            k8s_cache=k8s_cache,
            k8s_include_by_default=k8s_include_by_default,
            k8s_namespaces_to_exclude=k8s_namespaces_to_exclude,
            current_time=current_time
            )

class CRIEnumerator( ContainerEnumerator ):
    """
    Container Enumerator that retrieves the list of containers by querying the Kubelet API for a list of all pods on the node
    and then from the list of pods, retrieve all the relevant container information
    """
    def __init__( self, container_id, k8s_api_url, query_filesystem ):
        super( CRIEnumerator, self).__init__( container_id )
        k8s = KubernetesApi(k8s_api_url=k8s_api_url)
        self._kubelet = KubeletApi( k8s )
        self._query_filesystem = query_filesystem

        self._log_base = '/var/log/containers'
        self._container_glob = '%s/*.log' % self._log_base
        self._info_re = re.compile( '^%s/([^_]+)_([^_]+)_([^_]+)-([^_]+).log$' % self._log_base )

    def get_containers( self, running_or_created_after=None, glob_list=None, k8s_cache=None, k8s_include_by_default=True, k8s_namespaces_to_exclude=None, current_time=None ):
        result = {}
        container_info = []

        if k8s_namespaces_to_exclude is None:
            k8s_namespaces_to_exclude = []

        if current_time is None:
            current_time = time.time()

        try:
            # see if we should query the container list from the filesystem or the kubelet API
            if self._query_filesystem:
                container_info = self._get_containers_from_filesystem( k8s_namespaces_to_exclude )
            else:
                container_info = self._get_containers_from_kubelet( k8s_namespaces_to_exclude )

            # process the container info
            for pod_name, pod_namespace, cname, cid in container_info:
                short_cid = _get_short_cid( cid )

                # filter against the container glob list
                add_container = True
                if glob_list:
                    add_container = False
                    for glob in glob_list:
                        if fnmatch.fnmatch( cname, glob ):
                            add_container = True
                            break

                if not add_container:
                    global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' based on glob_list" % short_cid)
                    continue

                # build a k8s_info structure similar to the one built by _get_containers
                k8s_info = {}
                k8s_info['pod_name'] = pod_name
                k8s_info['pod_namespace'] = pod_namespace
                k8s_info['k8s_container_name'] = cname

                # get pod and deployment/controller information for the container
                if k8s_cache:
                    pod = k8s_cache.pod( pod_namespace, pod_name, current_time )
                    if pod:
                        # check to see if we should exclude this container
                        default_exclude = not k8s_include_by_default
                        exclude = pod.exclude_pod( container_name=cname, default=default_exclude)

                        # exclude if necessary
                        if exclude:
                            if pod.annotations:
                                global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' based on pod annotations, %s" % (short_cid, pod.annotations) )
                            continue

                        # add a debug message if containers are excluded by default but this container is included
                        if default_exclude and not exclude:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Including container '%s' based on pod annotations, %s" % (short_cid, pod.annotations) )

                        k8s_info['pod_info'] = pod
                        k8s_info['pod_uid'] = pod.uid

                # build the path to the log file on disk
                log_path = "%s/%s_%s_%s-%s.log" % (self._log_base, pod_name, pod_namespace, cname, cid)

                # add this container to the list of results
                result[cid] = {'name': cname, 'log_path': log_path, 'k8s_info': k8s_info }
        except Exception, e:
            global_log.error("Error querying containers %s - %s" % (str(e), traceback.format_exc()), limit_once_per_x_secs=300,
                         limit_key='query-cri-containers' )
        return result

    def _get_containers_from_filesystem( self, k8s_namespaces_to_exclude ):

        result = []

        # iterate over all files that match our container glob
        for filename in glob.iglob( self._container_glob ):

            # ignore any files that don't match the format we are expecting
            m = self._info_re.match( filename )
            if m is None:
                global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding file '%s' because the filename doesn't match the expected log format" % (filename) )
                continue

            # extract pod and container info
            pod_name = m.group(1)
            pod_namespace = m.group(2)
            cname = m.group(3)
            cid = m.group(4)

            # ignore any unwanted namespaces
            if pod_namespace in k8s_namespaces_to_exclude:
                global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' because namespace '%s' is excluded" % (cname, pod_namespace) )
                continue

            # ignore the scalyr-agent container
            if cid == self._container_id:
                global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container because cid '%s' is the scalyr_agent container" % _get_short_cid( cid ) )
                continue

            result.append( (pod_name, pod_namespace, cname, cid) )

        return result


    def _get_containers_from_kubelet( self, k8s_namespaces_to_exclude ):

        result = []

        try:
            # query the api
            response = self._kubelet.query_pods()
            pods = response.get( 'items', [] )

            # process the list of pods
            for pod in pods:
                metadata = pod.get( 'metadata', {} )
                pod_name = metadata.get( 'name', '' )
                pod_namespace = metadata.get( 'namespace', '' )
                pod_uid = metadata.get( 'uid', '' )

                # ignore anything that is in an excluded namespace
                if pod_namespace in k8s_namespaces_to_exclude:
                    global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding pod '%s' because namespace '%s' is excluded" % (pod_name, pod_namespace))
                    continue

                # get the list of containers for this pod
                status = pod.get( 'status', {} )
                containers = status.get( 'containerStatuses', [] )
                for container in containers:

                    # get the id of the container
                    cid = container.get( 'containerID' )
                    if cid is None:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container because no cid was found")
                        continue

                    # strip out the runtime component
                    m = _CID_RE.match( cid )
                    if m:
                        cid = m.group(2)
                    else:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container because cid didn't match expected format '<runtime>://<container id>'")
                        continue

                    short_cid = _get_short_cid( cid )

                    # ignore the scalyr-agent container
                    if cid == self._container_id:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container because cid '%s' is the scalyr_agent container" % short_cid )
                        continue

                    # make sure the container has a name
                    cname = container.get( 'name' )
                    if cname is None:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' because no container name was found" % short_cid)
                        continue

                    # we are only interested in running or terminated pods
                    cstate = container.get( 'state', {} )
                    if 'running' not in cstate and 'terminated' not in cstate:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Excluding container '%s' because not yet running" % short_cid )
                        continue

                    result.append( (pod_name, pod_namespace, cname, cid) )


        except ConnectionError, e:
            global_log.error("Error connecting to kubelet API endpoint - %s. The Scalyr Agent will now monitor containers from the filesystem" % str(e), limit_once_per_x_secs=300,
                         limit_key='kubelet-api-connect' )
            self._query_filesystem = True
        except Exception, e:
            global_log.error("Error querying kubelet API for running pods and containers", limit_once_per_x_secs=300,
                         limit_key='kubelet-api-query-pods' )

        return result

class ContainerChecker( StoppableThread ):
    """
        Monitors containers to check when they start and stop running.
    """

    def __init__( self, config, global_config, logger, socket_file, docker_api_version, host_hostname, data_path, log_path,
                  include_all, include_controller_info, namespaces_to_ignore,
                  ignore_pod_sandboxes ):

        self._config = config
        self._global_config = global_config
        self._logger = logger

        self.__delay = self._config.get( 'container_check_interval' )
        self.__log_prefix = self._config.get( 'docker_log_prefix' )
        self.__name = self._config.get( 'container_name' )

        self.__use_v2_attributes = self._config.get('k8s_use_v2_attributes')
        self.__use_v1_and_v2_attributes = self._config.get('k8s_use_v1_and_v2_attributes')

        # get the format for parsing logs
        self.__parse_format = self._config.get( 'k8s_parse_format' )

        # if the deprecated `k8s_parse_json` flag is set, that should override
        # the `k8s_parse_format` option on the basis that it would be a left over
        # value from an older configuration file and we want to maintain similar behavior
        parse_json = self._config.get( 'k8s_parse_json' )
        if parse_json is not None:
            if parse_json:
                self.__parse_format = 'auto'
            else:
                self.__parse_format = 'raw'

        self.__socket_file = socket_file
        self.__docker_api_version = docker_api_version
        self.__client = None
        self.__always_use_cri = self._config.get( 'k8s_always_use_cri' )
        self.__cri_query_filesystem = self._config.get( 'k8s_cri_query_filesystem' )

        self.container_id = None

        self.__log_path = log_path

        self.__host_hostname = host_hostname

        self.__readback_buffer_size = self._config.get( 'readback_buffer_size' )

        self.__glob_list = config.get( 'container_globs' )

        # The namespace whose logs we should not collect.
        self.__namespaces_to_ignore = namespaces_to_ignore

        self.__ignore_pod_sandboxes = ignore_pod_sandboxes

        # This is currently an experimental feature.  Including controller information for every event uploaded about
        # a pod (cluster name, controller name, controller labels)
        self.__include_controller_info = include_controller_info

        self.containers = {}
        self.__include_all = include_all

        self.__k8s_cache_init_abort_delay = self._config.get( 'k8s_cache_init_abort_delay' )

        self.k8s_cache = None

        self.__log_watcher = None
        self.__module = None
        self.__start_time = time.time()
        self.__thread = StoppableThread( target=self.check_containers, name="Container Checker" )
        self._container_enumerator = None
        self._container_runtime = 'unknown'

    def _is_running_in_docker( self ):
        """
        Checks to see if the agent is running inside a docker container
        """
        # whether or not we are running inside docker can be determined
        # by the existence of the file /.dockerenv
        return os.path.exists( "/.dockerenv" )

    def start( self ):

        try:
            k8s_api_url = self._config.get('k8s_api_url')
            k8s_verify_api_queries = self._config.get( 'k8s_verify_api_queries' )

            # create the k8s cache
            self.k8s_cache = k8s_utils.cache( self._global_config )

            delay = 0.5
            message_delay = 5
            start_time = time.time()
            message_time = start_time
            abort = False

            # wait until the k8s_cache is initialized before aborting
            while not self.k8s_cache.is_initialized():
                time.sleep( delay )
                current_time = time.time()
                # see if we need to print a message
                elapsed = current_time - message_time
                if elapsed > message_delay:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_0, 'start() - waiting for Kubernetes cache to be initialized' )
                    message_time = current_time

                # see if we need to abort the monitor because we've been waiting too long for init
                elapsed = current_time - start_time
                if elapsed > self.__k8s_cache_init_abort_delay:
                    abort = True
                    break

            if abort:
                raise K8sInitException( "Unable to initialize kubernetes cache" )

            # check to see if the user has manually specified a cluster name, and if so then
            # force enable 'Starbuck' features
            if self.k8s_cache.get_cluster_name() is not None:
                self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "ContainerChecker - cluster name detected, enabling v2 attributes and controller information" )
                self.__use_v2_attributes = True
                self.__include_controller_info = True

            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )

            self.container_id = self.k8s_cache.get_agent_container_id() or 'unknown'
            self._container_runtime = self.k8s_cache.get_container_runtime() or 'unknown'
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Container runtime is '%s'" % (self._container_runtime) )

            if self._container_runtime == 'docker' and not self.__always_use_cri:
                self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )
                self._container_enumerator = DockerEnumerator( self.__client, self.container_id )
            else:
                self._container_enumerator = CRIEnumerator( self.container_id, k8s_api_url, query_filesystem=self.__cri_query_filesystem )

            if self.__parse_format == 'auto':
                # parse in json if we detect the container runtime to be 'docker' or if we detect
                # that we are running in docker
                if self._container_runtime == 'docker' or self._is_running_in_docker():
                    self.__parse_format = 'json'
                else:
                    self.__parse_format = 'cri'

            self.containers = self._container_enumerator.get_containers(
                glob_list=self.__glob_list,
                k8s_cache=self.k8s_cache,
                k8s_include_by_default=self.__include_all,
                k8s_namespaces_to_exclude=self.__namespaces_to_ignore
                )

            # if querying the docker api fails, set the container list to empty
            if self.containers is None:
                self.containers = {}

            self.raw_logs = []

            self.docker_logs = self.__get_docker_logs( self.containers, self.k8s_cache )

            #create and start the DockerLoggers
            self.__start_docker_logs( self.docker_logs )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Initialization complete.  Starting k8s monitor for Scalyr" )
            self.__thread.start()

        except K8sInitException, e:
            global_log.warn( "Failed to start container checker - %s. Aborting kubernetes_monitor" % (str(e)) )
            raise
        except Exception, e:
            global_log.warn( "Failed to start container checker - %s\n%s" % (str(e), traceback.format_exc() ))


    def stop( self, wait_on_join=True, join_timeout=5 ):
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers

        for logger in self.raw_logs:
            path = logger['log_config']['path']
            if self.__log_watcher:
                self.__log_watcher.remove_log_path( self.__module.module_name, path )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping %s" % (path) )

        self.raw_logs = []

    def get_k8s_data( self ):
        """ Convenience wrapper to query and process all pods
            and pods retreived by the k8s API.
            A filter is used to limit pods returned to those that
            are running on the current node

            @return: a dict keyed by namespace, whose values are a dict of pods inside that namespace, keyed by pod name
        """
        result = {}
        try:
            result = self.k8s_cache.pods_shallow_copy()
        except Exception, e:
            global_log.warn( "Failed to get k8s data: %s\n%s" % (str(e), traceback.format_exc() ),
                         limit_once_per_x_secs=300, limit_key='get_k8s_data' )
        return result

    def check_containers( self, run_state ):
        """Update thread for monitoring docker containers and the k8s info such as labels
        """

        # Assert that the cache has been initialized
        if not self.k8s_cache.is_initialized():
            self._logger.log(scalyr_logging.DEBUG_LEVEL_0, 'container_checker - Kubernetes cache not initialized' )
            raise K8sInitException( "check_container - Kubernetes cache not initialized. Aborting" )

        # store the digests from the previous iteration of the main loop to see
        # if any pod information has changed
        prev_digests = {}
        base_attributes = self.__get_base_attributes()
        previous_time = time.time()

        while run_state.is_running():
            try:


                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )

                current_time = time.time()

                running_containers = self._container_enumerator.get_containers(
                    running_or_created_after=previous_time,
                    glob_list=self.__glob_list,
                    k8s_cache=self.k8s_cache,
                    k8s_include_by_default=self.__include_all,
                    k8s_namespaces_to_exclude=self.__namespaces_to_ignore,
                    current_time=current_time
                )

                previous_time = current_time - 1

                # if running_containers is None, that means querying the docker api failed.
                # rather than resetting the list of running containers to empty
                # continue using the previous list of containers
                if running_containers is None:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Failed to get list of containers')
                    running_containers = self.containers

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Found %d containers' % len(running_containers))
                #get the containers that have started since the last sample
                starting = {}
                changed = {}
                digests = {}

                for cid, info in running_containers.iteritems():
                    pod = None
                    if 'k8s_info' in info:
                        pod_name = info['k8s_info'].get( 'pod_name', 'invalid_pod' )
                        pod_namespace = info['k8s_info'].get( 'pod_namespace', 'invalid_namespace' )
                        pod = info['k8s_info'].get( 'pod_info', None )

                        if not pod:
                            self._logger.warning( "No pod info for container %s.  pod: '%s/%s'" % (_get_short_cid( cid ), pod_namespace, pod_name),
                                                  limit_once_per_x_secs=300,
                                                  limit_key='check-container-pod-info-%s' % cid)

                    # start the container if have a container that wasn't running
                    if cid not in self.containers:
                        self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Starting loggers for container '%s'" % info['name'] )
                        starting[cid] = info
                    elif cid in prev_digests:
                        # container was running and it exists in the previous digest dict, so see if
                        # it has changed
                        if pod and prev_digests[cid] != pod.digest:
                            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Pod digest changed for '%s'" % info['name'] )
                            changed[cid] = info

                    # store the digest from this iteration of the loop
                    if pod:
                        digests[cid] = pod.digest

                #get the containers that have stopped
                stopping = {}
                for cid, info in self.containers.iteritems():
                    if cid not in running_containers:
                        self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping logger for container '%s' (%s)" % (info['name'], cid[:6] ) )
                        stopping[cid] = info

                #stop the old loggers
                self.__stop_loggers( stopping )

                #update the list of running containers
                #do this before starting new ones, as starting up new ones
                #will access self.containers
                self.containers = running_containers

                #start the new ones
                self.__start_loggers( starting, self.k8s_cache )

                prev_digests = digests

                # update the log config for any changed containers
                if self.__log_watcher:
                    for logger in self.raw_logs:
                        if logger['cid'] in changed:
                            info = changed[logger['cid']]
                            new_config = self.__get_log_config_for_container( logger['cid'], info, self.k8s_cache, base_attributes )
                            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "updating config for '%s'" % info['name'] )
                            self.__log_watcher.update_log_config( self.__module.module_name, new_config )
            except Exception, e:
                self._logger.warn( "Exception occurred when checking containers %s\n%s" % (str( e ), traceback.format_exc()) )

            run_state.sleep_but_awaken_if_stopped( self.__delay )


    def set_log_watcher( self, log_watcher, module ):
        self.__log_watcher = log_watcher
        self.__module = module

    def __stop_loggers( self, stopping ):
        """
        Stops any DockerLoggers in the 'stopping' dict
        @param: stopping - a dict of container ids => container names. Any running containers that have
        the same container-id as a key in the dict will be stopped.
        """
        if stopping:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Stopping all docker loggers')


            # go through all the raw logs and see if any of them exist in the stopping list, and if so, stop them
            for logger in self.raw_logs:
                cid = logger['cid']
                if cid in stopping:
                    path = logger['log_config']['path']
                    if self.__log_watcher:
                        self.__log_watcher.schedule_log_path_for_removal( self.__module.module_name, path )

            self.raw_logs[:] = [l for l in self.raw_logs if l['cid'] not in stopping]
            self.docker_logs[:] = [l for l in self.docker_logs if l['cid'] not in stopping]

    def __start_loggers( self, starting, k8s_cache ):
        """
        Starts a list of DockerLoggers
        @param: starting - a list of DockerLoggers to start
        """
        if starting:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Starting all docker loggers')
            docker_logs = self.__get_docker_logs( starting, k8s_cache )
            self.__start_docker_logs( docker_logs )
            self.docker_logs.extend( docker_logs )

    def __start_docker_logs( self, docker_logs ):
        for log in docker_logs:
            if self.__log_watcher:
                log['log_config'] = self.__log_watcher.add_log_config( self.__module, log['log_config'] )

            self.raw_logs.append( log )

    def __get_last_request_for_log( self, path ):
        result = datetime.datetime.fromtimestamp( self.__start_time )

        try:
            full_path = os.path.join( self.__log_path, path )
            fp = open( full_path, 'r', self.__readback_buffer_size )

            # seek readback buffer bytes from the end of the file
            fp.seek( 0, os.SEEK_END )
            size = fp.tell()
            if size < self.__readback_buffer_size:
                fp.seek( 0, os.SEEK_SET )
            else:
                fp.seek( size - self.__readback_buffer_size, os.SEEK_SET )

            first = True
            for line in fp:
                # ignore the first line because it likely started somewhere randomly
                # in the line
                if first:
                    first = False
                    continue

                dt, _ = _split_datetime_from_line( line )
                if dt:
                    result = dt
            fp.close()
        except Exception, e:
            global_log.info( "%s", str(e) )

        return scalyr_util.seconds_since_epoch( result )

    def __create_log_config( self, parser, path, attributes, parse_format='raw' ):
        """Convenience function to create a log_config dict from the parameters"""

        return { 'parser': parser,
                 'path': path,
                 'parse_format' : parse_format,
                 'attributes': attributes
               }

    def __get_base_attributes( self ):
        attributes = None
        try:
            attributes = JsonObject( { "monitor": "agentKubernetes" } )
            if self.__host_hostname:
                attributes['serverHost'] = self.__host_hostname

        except Exception, e:
            self._logger.error( "Error setting monitor attribute in KubernetesMonitor" )
            raise

        return attributes

    def __get_log_config_for_container( self, cid, info, k8s_cache, base_attributes ):
        result = None

        container_attributes = base_attributes.copy()
        if not self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
            container_attributes['containerName'] = info['name']
            container_attributes['containerId'] = cid
        elif self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
            container_attributes['container_id'] = cid
        parser = 'docker'
        common_annotations = {}
        container_annotations = {}
        # pod name and namespace are set to an invalid value for cases where errors occur and a log
        # message is produced, so that the log message has clearly invalid values for these rather
        # than just being empty
        pod_name = '--'
        pod_namespace = '--'
        short_cid = _get_short_cid( cid )

        # dict of available substitutions for the rename_logfile field
        rename_vars = {
            'short_id' : short_cid,
            'container_id' : cid,
            'container_name' : info['name'],
        }

        k8s_info = info.get( 'k8s_info', {} )

        if k8s_info:
            pod_name = k8s_info.get('pod_name', 'invalid_pod')
            pod_namespace = k8s_info.get('pod_namespace', 'invalid_namespace')
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "got k8s info for container %s, '%s/%s'" % (short_cid, pod_namespace, pod_name) )
            pod = k8s_cache.pod( pod_namespace, pod_name )
            if pod:
                rename_vars['pod_name'] = pod.name
                rename_vars['namespace'] = pod.namespace
                rename_vars['node_name'] = pod.node_name

                container_attributes['pod_name'] = pod.name
                container_attributes['pod_namespace'] = pod.namespace
                container_attributes['pod_uid'] = pod.uid
                if not self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
                    container_attributes['node_name'] = pod.node_name
                elif self.__use_v2_attributes or self.__use_v1_and_v2_attributes:
                    container_attributes['k8s_node'] = pod.node_name
                container_attributes['scalyr-category'] = 'log'

                for label, value in pod.labels.iteritems():
                    container_attributes[label] = value

                if 'parser' in pod.labels:
                    parser = pod.labels['parser']

                # get the controller information if any
                if pod.controller is not None:
                    controller = pod.controller
                    # for backwards compatibility allow both deployment_name and controller_name here
                    rename_vars['deployment_name'] = controller.name
                    rename_vars['controller_name'] = controller.name
                    if self.__include_controller_info:
                        container_attributes['_k8s_dn'] = controller.name
                        container_attributes['_k8s_dl'] = controller.flat_labels
                        container_attributes['_k8s_ck'] = controller.kind

                # get the cluster name
                cluster_name = k8s_cache.get_cluster_name()
                if self.__include_controller_info and cluster_name is not None:
                    container_attributes['_k8s_cn'] = cluster_name

                # get the annotations of this pod as a dict.
                # by default all annotations will be applied to all containers
                # in the pod
                all_annotations = pod.annotations
                container_specific_annotations = False

                # get any common annotations for all containers
                for annotation, value in all_annotations.iteritems():
                    if annotation in pod.container_names:
                        container_specific_annotations = True
                    else:
                        common_annotations[annotation] = value

                # now get any container specific annotations
                # for this container
                if container_specific_annotations:
                    k8s_container_name = k8s_info.get('k8s_container_name', '')
                    if k8s_container_name in all_annotations:
                        # get the annotations for this container
                        container_annotations = all_annotations[k8s_container_name]

                        # sanity check to make sure annotations are either a JsonObject or dict
                        if not isinstance( container_annotations, JsonObject ) and not isinstance( container_annotations, dict ):
                            self._logger.warning( "Unexpected configuration found in annotations for pod '%s/%s'.  Expected a dict for configuration of container '%s', but got a '%s' instead. No container specific configuration options applied." % ( pod.namespace, pod.name, k8s_container_name, str( type(container_annotations) ) ),
                                                  limit_once_per_x_secs=300,
                                                  limit_key='k8s-invalid-container-config-%s' % cid)
                            container_annotations = {}

            else:
                self._logger.warning( "Couldn't map container '%s' to pod '%s/%s'. Logging limited metadata from docker container labels instead." % ( short_cid, pod_namespace, pod_name ),
                                    limit_once_per_x_secs=300,
                                    limit_key='k8s-docker-mapping-%s' % cid)
                container_attributes['pod_name'] = pod_name
                container_attributes['pod_namespace'] = pod_namespace
                container_attributes['pod_uid'] = k8s_info.get('pod_uid', 'invalid_uid')
                container_attributes['k8s_container_name'] = k8s_info.get('k8s_container_name', 'invalid_container_name')
        else:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "no k8s info for container %s" % short_cid )

        if 'log_path' in info and info['log_path']:
            result = self.__create_log_config( parser=parser, path=info['log_path'], attributes=container_attributes, parse_format=self.__parse_format )
            result['rename_logfile'] = '/%s/%s.log' % (self._container_runtime, info['name'])
            # This is for a hack to prevent the original log file name from being added to the attributes.
            if self.__use_v2_attributes and not self.__use_v1_and_v2_attributes:
                result['rename_no_original'] = True
        else:
            # without a log_path there is no log config that can be created.  Log a warning and return
            # See ticket: #AGENT-88
            self._logger.warning( "No log path found for container '%s' of %s/%s" % (short_cid, pod_namespace, pod_name ),
                                    limit_once_per_x_secs=3600,
                                    limit_key='k8s-invalid-log-path-%s' % short_cid)
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Info is: %s\nCommon annotations: %s\nContainer annotations: %s" % (info, common_annotations, container_annotations),
                                    limit_once_per_x_secs=3600,
                                    limit_key='k8s-invalid-log-path-info-%s' % short_cid)

            return None

        if result is None:
            # This should never be true because either we have created a result based on the log path
            # or we have returned early, however it is here to protect against processing annotations
            # on an empty result.  See ticket: #AGENT-88
            self._logger.warning( "Empty result for container '%s' of %s/%s" % (short_cid, pod_namespace, pod_name ),
                                    limit_once_per_x_secs=3600,
                                    limit_key='k8s-empty-result-%s' % short_cid)
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Info is: %s\nCommon annotations: %s\nContainer annotations: %s" % (info, common_annotations, container_annotations),
                                    limit_once_per_x_secs=3600,
                                    limit_key='k8s-empty-result-info-%s' % short_cid)
            return None

        # apply common annotations first
        annotations = common_annotations
        # set/override any container specific annotations
        annotations.update( container_annotations )

        # ignore include/exclude options which have special
        # handling in the log_config verification that expects a different type than the one used in the nnotations
        skip_keys = [ 'include', 'exclude' ]

        # list of config items that cannot be updated via annotations
        invalid_keys = [ 'path', 'lineGroupers' ]

        # set config items, ignoring invalid options and taking care to
        # handle attributes
        for key, value in annotations.iteritems():
            if key in skip_keys:
                continue

            if key in invalid_keys:
                self._logger.warning( "Invalid key '%s' found in annotation config for '%s/%s'. Configuration of '%s' is not currently supported via annotations and has been ignored." % (key, pod_namespace, pod_name, key ),
                                    limit_once_per_x_secs=300,
                                    limit_key='k8s-invalid-annotation-config-key-%s' % key)
                continue

            # we need to make sure we update attributes rather
            # than overriding the entire dict, otherwise we'll override pod_name, namespace etc
            if key == 'attributes':
                if 'attributes' not in result:
                    result['attributes'] = {}
                attrs = result['attributes']
                attrs.update( value )

                # we also need to override the top level parser value if attributes['parser'] is set
                if 'parser' in attrs:
                    result['parser'] = attrs['parser']
                continue
            elif key == 'rename_logfile':
                # rename logfile supports string substitions
                # so update value if necessary
                template = Template( value )
                value = template.safe_substitute( rename_vars )

            # everything else is added to the log_config result as is
            result[key] = value

        return result

    def __get_docker_logs( self, containers, k8s_cache ):
        """Returns a list of dicts containing the container id, stream, and a log_config
        for each container in the 'containers' param.
        """

        result = []

        attributes = self.__get_base_attributes()

        prefix = self.__log_prefix + '-'

        for cid, info in containers.iteritems():
            log_config = self.__get_log_config_for_container( cid, info, k8s_cache, attributes )
            if log_config:
                result.append( { 'cid': cid, 'stream': 'raw', 'log_config': log_config } )

        return result

class KubernetesMonitor( ScalyrMonitor ):
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
    def __get_socket_file( self ):
        """Gets the Docker API socket file and validates that it is a UNIX socket
        """
        #make sure the API socket exists and is a valid socket
        api_socket = self._config.get( 'api_socket' )
        try:
            st = os.stat( api_socket )
            if not stat.S_ISSOCK( st.st_mode ):
                raise Exception()
        except:
            raise Exception( "The file '%s' specified by the 'api_socket' configuration option does not exist or is not a socket.\n\tPlease make sure you have mapped the docker socket from the host to this container using the -v parameter.\n\tNote: Due to problems Docker has mapping symbolic links, you should specify the final file and not a path that contains a symbolic link, e.g. map /run/docker.sock rather than /var/run/docker.sock as on many unices /var/run is a symbolic link to the /run directory." % api_socket )

        return api_socket

    def _initialize( self ):
        data_path = ""
        log_path = ""
        host_hostname = ""

        # Since getting metrics from Docker takes a non-trivial amount of time, we will deduct the time spent
        # in gathering the metric samples from the time we should sleep so that we do gather a sample once every
        # sample_interval_secs
        self._adjust_sleep_by_gather_time = True

        # Override the default value for the rate limit for writing the metric logs.  We override it to set no limit
        # because it is fairly difficult to bound this since the log will emit X metrics for every pod being monitored.
        self._log_write_rate = self._config.get('monitor_log_write_rate', convert_to=int, default=-1)
        self._log_max_write_burst = self._config.get('monitor_log_max_write_burst', convert_to=int, default=-1)

        if self._global_config:
            data_path = self._global_config.agent_data_path
            log_path = self._global_config.agent_log_path

            if self._global_config.server_attributes:
                if 'serverHost' in self._global_config.server_attributes:
                    host_hostname = self._global_config.server_attributes['serverHost']
                else:
                    self._logger.info( "no server host in server attributes" )
            else:
                self._logger.info( "no server attributes in global config" )

        parse_format = self._config.get( 'k8s_parse_format' )
        if parse_format not in ['auto', 'raw', 'json', 'cri']:
            raise BadMonitorConfiguration( "k8s_parse_format must be one of 'auto', 'json', 'cri' or 'raw'.  Current value is: %s" % parse_format, 'k8s_parse_format' )

        # The namespace whose logs we should not collect.
        self.__namespaces_to_ignore = []
        for x in self._config.get('k8s_ignore_namespaces').split():
            self.__namespaces_to_ignore.append(x.strip())

        self.__ignore_pod_sandboxes = self._config.get('k8s_ignore_pod_sandboxes')
        self.__socket_file = self.__get_socket_file()
        self.__docker_api_version = self._config.get( 'docker_api_version' )
        self.__k8s_api_url = self._config.get('k8s_api_url')
        self.__docker_max_parallel_stats = self._config.get('docker_max_parallel_stats')
        self.__client = None
        self.__metric_fetcher = None

        self.__glob_list = self._config.get( 'container_globs' )
        self.__include_all = self._config.get( 'k8s_include_all_containers' )

        self.__report_container_metrics = self._config.get('report_container_metrics')
        self.__report_k8s_metrics = self._config.get('report_k8s_metrics') and self.__report_container_metrics
        # Object for talking to the kubelet server running on this localhost.  This is used to gather metrics only
        # available via the kubelet.
        self.__kubelet_api = None
        self.__gather_k8s_pod_info = self._config.get('gather_k8s_pod_info')

        # Including controller information for every event uploaded about  a pod (cluster name, controller name,
        # controller labels)
        self.__include_controller_info = self._config.get('include_deployment_info', convert_to=bool, default=False)

        self.__container_checker = None
        if self._config.get('log_mode') != 'syslog':
            self.__container_checker = ContainerChecker( self._config, self._global_config, self._logger, self.__socket_file,
                                                         self.__docker_api_version, host_hostname, data_path, log_path,
                                                         self.__include_all, self.__include_controller_info,
                                                         self.__namespaces_to_ignore, self.__ignore_pod_sandboxes )

        # Metrics provided by the kubelet API.
        self.__k8s_pod_network_metrics = {
            'k8s.pod.network.rx_bytes': 'rxBytes',
            'k8s.pod.network.rx_errors': 'rxErrors',
            'k8s.pod.network.tx_bytes': 'txBytes',
            'k8s.pod.network.tx_errors': 'txErrors',
        }

        # Metrics provide by the kubelet API.
        self.__k8s_node_network_metrics = {
            'k8s.node.network.rx_bytes': 'rxBytes',
            'k8s.node.network.rx_errors': 'rxErrors',
            'k8s.node.network.tx_bytes': 'txBytes',
            'k8s.node.network.tx_errors': 'txErrors',
        }

        # All the docker. metrics are provided by the docker API.
        self.__network_metrics = self.__build_metric_dict( 'docker.net.', [
            "rx_bytes",
            "rx_dropped",
            "rx_errors",
            "rx_packets",
            "tx_bytes",
            "tx_dropped",
            "tx_errors",
            "tx_packets",
        ])

        self.__mem_stat_metrics = self.__build_metric_dict( 'docker.mem.stat.', [
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
            "total_pgpgin"
        ])

        self.__mem_metrics = self.__build_metric_dict( 'docker.mem.', [
            "max_usage",
            "usage",
            "fail_cnt",
            "limit"
        ])

        self.__cpu_usage_metrics = self.__build_metric_dict( 'docker.cpu.', [
            "usage_in_usermode",
            "total_usage",
            "usage_in_kernelmode"
        ])

        self.__cpu_throttling_metrics = self.__build_metric_dict( 'docker.cpu.throttling.', [
            "periods",
            "throttled_periods",
            "throttled_time"
        ])


    def set_log_watcher( self, log_watcher ):
        """Provides a log_watcher object that monitors can use to add/remove log files
        """
        if self.__container_checker:
            self.__container_checker.set_log_watcher( log_watcher, self )

    def __build_metric_dict( self, prefix, names ):
        result = {}
        for name in names:
            result["%s%s"%(prefix, name)] = name
        return result

    def __log_metrics( self, monitor_override, metrics_to_emit, metrics, extra=None ):
        if metrics is None:
            return

        for key, value in metrics_to_emit.iteritems():
            if value in metrics:
                # Note, we do a bit of a hack to pretend the monitor's name include the container/pod's name.  We take this
                # approach because the Scalyr servers already have some special logic to collect monitor names and ids
                # to help auto generate dashboards.  So, we want a monitor name like `docker_monitor(foo_container)`
                # for each running container.
                self._logger.emit_value( key, metrics[value], extra, monitor_id_override=monitor_override )

    def __log_network_interface_metrics( self, container, metrics, interface=None, k8s_extra={} ):
        """ Logs network interface metrics

            @param: container - name of the container the log originated from
            @param: metrics - a dict of metrics keys/values to emit
            @param: interface - an optional interface value to associate with each metric value emitted
            @param: k8s_extra - extra k8s specific key/value pairs to associate with each metric value emitted
        """
        extra = None
        if interface:
            if k8s_extra is None:
                extra = {}
            else:
                extra = k8s_extra.copy()

            extra['interface'] = interface

        self.__log_metrics( container, self.__network_metrics, metrics, extra )

    def __log_memory_stats_metrics( self, container, metrics, k8s_extra ):
        """ Logs memory stats metrics

            @param: container - name of the container the log originated from
            @param: metrics - a dict of metrics keys/values to emit
            @param: k8s_extra - extra k8s specific key/value pairs to associate with each metric value emitted
        """
        if 'stats' in metrics:
            self.__log_metrics( container, self.__mem_stat_metrics, metrics['stats'], k8s_extra )

        self.__log_metrics( container, self.__mem_metrics, metrics, k8s_extra )

    def __log_cpu_stats_metrics( self, container, metrics, k8s_extra ):
        """ Logs cpu stats metrics

            @param: container - name of the container the log originated from
            @param: metrics - a dict of metrics keys/values to emit
            @param: k8s_extra - extra k8s specific key/value pairs to associate with each metric value emitted
        """
        if 'cpu_usage' in metrics:
            cpu_usage = metrics['cpu_usage']
            if 'percpu_usage' in cpu_usage:
                percpu = cpu_usage['percpu_usage']
                count = 1
                if percpu:
                    for usage in percpu:
                        # Use dev for the CPU number since it is a known tag for Scalyr to use in delta computation.
                        extra = { 'dev' : count }
                        if k8s_extra is not None:
                            extra.update(k8s_extra)
                        self._logger.emit_value( 'docker.cpu.usage', usage, extra, monitor_id_override=container )
                        count += 1
            self.__log_metrics( container, self.__cpu_usage_metrics, cpu_usage, k8s_extra )

        if 'system_cpu_usage' in metrics:
            self._logger.emit_value( 'docker.cpu.system_cpu_usage', metrics['system_cpu_usage'], k8s_extra,
                                     monitor_id_override=container )

        if 'throttling_data' in metrics:
            self.__log_metrics( container, self.__cpu_throttling_metrics, metrics['throttling_data'], k8s_extra )

    def __log_json_metrics( self, container, metrics, k8s_extra ):
        """ Log docker metrics based on the JSON response returned from querying the Docker API

            @param: container - name of the container the log originated from
            @param: metrics - a dict of metrics keys/values to emit
            @param: k8s_extra - extra k8s specific key/value pairs to associate with each metric value emitted
        """
        for key, value in metrics.iteritems():
            if value is None:
                continue

            if key == 'networks':
                for interface, network_metrics in value.iteritems():
                    self.__log_network_interface_metrics( container, network_metrics, interface, k8s_extra=k8s_extra )
            elif key == 'network':
                self.__log_network_interface_metrics( container, value, k8s_extra )
            elif key == 'memory_stats':
                self.__log_memory_stats_metrics( container, value, k8s_extra )
            elif key == 'cpu_stats':
                self.__log_cpu_stats_metrics( container, value, k8s_extra )

    def __gather_metrics_from_api_for_container( self, container, k8s_extra ):
        """ Query the Docker API for container metrics

            @param: container - name of the container to query
            @param: k8s_extra - extra k8s specific key/value pairs to associate with each metric value emitted
        """
        result = self.__metric_fetcher.get_metrics(container)
        if result is not None:
            self.__log_json_metrics( container, result, k8s_extra )

    def __build_k8s_controller_info( self, pod ):
        """
            Builds a dict containing information about the controller settings for a given pod

            @param: pod - a PodInfo object containing basic information (namespace/name) about the pod to query

            @return: a dict containing the controller name for the controller running
                     the specified pod, or an empty dict if the pod is not part of a controller
        """
        k8s_extra = {}
        if pod is not None:

            # default key and controlle name
            key = 'k8s-controller'
            name = 'none'

            # check if we have a controller, and if so use it
            controller = pod.controller
            if controller is not None:

                # use one of the predefined key if this is a controller kind we know about
                if controller.kind in _CONTROLLER_KEYS:
                    key = _CONTROLLER_KEYS[controller.kind]

                name = controller.name

            k8s_extra = {
                key: name
            }
        return k8s_extra

    def __get_k8s_controller_info( self, container ):
        """
            Gets information about the kubernetes controller of a given container
            @param: container - a dict containing information about a container, returned by _get_containers
        """
        k8s_info = container.get( 'k8s_info', {} )
        pod = k8s_info.get( 'pod_info', None )
        if pod is None:
            return None
        return self.__build_k8s_controller_info( pod )


    def __get_cluster_info( self, cluster_name ):
        """ returns a dict of values about the cluster """
        cluster_info = {}
        if self.__include_controller_info and cluster_name is not None:
            cluster_info['k8s-cluster'] = cluster_name

        return cluster_info

    def __gather_metrics_from_api( self, containers, cluster_name ):

        cluster_info = self.__get_cluster_info( cluster_name )

        for cid, info in containers.iteritems():
            self.__metric_fetcher.prefetch_metrics(info['name'])

        for cid, info in containers.iteritems():
            k8s_extra = {}
            if self.__include_controller_info:
                k8s_extra = self.__get_k8s_controller_info( info )
                if k8s_extra is not None:
                    k8s_extra.update( cluster_info )
                    k8s_extra.update({'pod_uid': info['name']})
                else:
                    k8s_extra = {}
            self.__gather_metrics_from_api_for_container( info['name'], k8s_extra )

    def __gather_k8s_metrics_for_node( self, node, extra ):
        """
            Gathers metrics from a Kubelet API response for a specific pod

            @param: node_metrics - A JSON Object from a response to a Kubelet API query
            @param: extra - Extra fields to append to each metric
        """

        name = node.get( "nodeName", None )
        if name is None:
            return

        node_extra = {
          'node_name': name
        }
        node_extra.update(extra)

        for key, metrics in node.iteritems():
            if key == 'network':
                self.__log_metrics( name, self.__k8s_node_network_metrics, metrics, node_extra )

    def __gather_k8s_metrics_for_pod( self, pod_metrics, pod_info, k8s_extra ):
        """
            Gathers metrics from a Kubelet API response for a specific pod

            @param: pod_metrics - A JSON Object from a response to a Kubelet API query
            @param: pod_info - A PodInfo structure regarding the pod in question
            @param: k8s_extra - Extra k8s specific fields to append to each metric
        """

        extra = {
            'pod_uid': pod_info.uid
        }

        extra.update( k8s_extra )

        for key, metrics in pod_metrics.iteritems():
            if key == 'network':
                self.__log_metrics( pod_info.uid, self.__k8s_pod_network_metrics, metrics, extra )

    def __gather_k8s_metrics_from_kubelet( self, containers, kubelet_api, cluster_name ):
        """
            Gathers k8s metrics from a response to a stats query of the Kubelet API

            @param: containers - a dict returned by _get_containers with info for all containers we are interested in
            @param: kubelet_api - a KubeletApi object for querying the KubeletApi
            @param: cluster_name - the name of the k8s cluster

        """

        cluster_info = self.__get_cluster_info( cluster_name )

        # get set of pods we are interested in querying
        pod_info = {}
        for cid, info in containers.iteritems():
            k8s_info = info.get( 'k8s_info', {} )
            pod = k8s_info.get( 'pod_info', None )
            if pod is None:
                continue

            pod_info[pod.uid] = pod

        try:
            stats = kubelet_api.query_stats()
            node = stats.get( 'node', {} )

            if node:
                self.__gather_k8s_metrics_for_node( node, cluster_info )

            pods = stats.get( 'pods', [] )

            # process pod stats, skipping any that are not in our list
            # of pod_info
            for pod in pods:
                pod_ref = pod.get( 'podRef', {} )
                pod_uid = pod_ref.get( 'uid', '<invalid>' )
                if pod_uid not in pod_info:
                    continue

                info = pod_info[pod_uid]
                controller_info = {}
                if self.__include_controller_info:
                    controller_info = self.__build_k8s_controller_info( info )
                    controller_info.update( cluster_info )
                self.__gather_k8s_metrics_for_pod( pod, info, controller_info )

        except ConnectionError, e:
            self._logger.warning( "Error connecting to kubelet API: %s.  No Kubernetes stats will be available" % str( e ),
                                  limit_once_per_x_secs=3600,
                                  limit_key='kubelet-api-connection-stats' )
        except KubeletApiException, e:
            self._logger.warning( "Error querying kubelet API: %s" % str( e ),
                                  limit_once_per_x_secs=300,
                                  limit_key='kubelet-api-query-stats' )

    def __get_k8s_cache(self):
        k8s_cache = None
        if self.__container_checker:
            k8s_cache = self.__container_checker.k8s_cache
        return k8s_cache

    def get_user_agent_fragment(self):
        """This method is periodically invoked by a separate (MonitorsManager) thread and must be thread safe.
        """
        k8s_cache = self.__get_k8s_cache()
        ver = None
        runtime = None
        if k8s_cache:
            ver = k8s_cache.get_api_server_version()
            runtime = k8s_cache.get_container_runtime()
        ver = 'k8s=%s' % (ver if ver else 'true')
        if runtime:
            ver += ';k8s-runtime=%s' % runtime

        return ver

    def gather_sample( self ):
        k8s_cache = self.__get_k8s_cache()

        cluster_name = None
        if k8s_cache is not None:
            cluster_name = k8s_cache.get_cluster_name()

        # gather metrics
        containers = None
        if self.__report_container_metrics and self.__client:
            containers = _get_containers(self.__client, ignore_container=None, glob_list=self.__glob_list,
                                         k8s_cache=k8s_cache, k8s_include_by_default=self.__include_all,
                                         k8s_namespaces_to_exclude=self.__namespaces_to_ignore)
        try:
            if containers:
                if self.__report_container_metrics:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve metrics for %d containers' % len(containers))
                    self.__gather_metrics_from_api( containers, cluster_name )

                if self.__report_k8s_metrics:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve k8s metrics %d' % len(containers))
                    self.__gather_k8s_metrics_from_kubelet( containers, self.__kubelet_api, cluster_name )
        except Exception, e:
            self._logger.exception( "Unexpected error logging metrics: %s" %( str(e) ) )

        if self.__gather_k8s_pod_info:
            cluster_info = self.__get_cluster_info( cluster_name )

            containers = self._container_enumerator.get_containers(
                                          k8s_cache=k8s_cache,
                                          k8s_include_by_default=self.__include_all,
                                          k8s_namespaces_to_exclude=self.__namespaces_to_ignore)
            for cid, info in containers.iteritems():
                try:
                    extra = info.get( 'k8s_info', {} )
                    extra['status'] = info.get('status', 'unknown')
                    if self.__include_controller_info:
                        controller = self.__get_k8s_controller_info( info )
                        extra.update( controller )
                        extra.update( cluster_info )

                    namespace = extra.get( 'pod_namespace', 'invalid-namespace' )
                    self._logger.emit_value( '%s.container_name' % (self._container_runtime), info['name'], extra, monitor_id_override="namespace:%s" % namespace )
                except Exception, e:
                    self._logger.error( "Error logging container information for %s: %s" % (_get_short_cid( cid ), str( e )) )

            if self.__container_checker:
                namespaces = self.__container_checker.get_k8s_data()
                for namespace, pods in namespaces.iteritems():
                    for pod_name, pod in pods.iteritems():
                        try:
                            extra = { 'pod_uid': pod.uid,
                                      'pod_namespace': pod.namespace,
                                      'node_name': pod.node_name }

                            if self.__include_controller_info:
                                controller_info = self.__build_k8s_controller_info( pod )
                                if controller_info:
                                    extra.update( controller_info )
                                extra.update( cluster_info )

                            self._logger.emit_value( 'k8s.pod', pod.name, extra, monitor_id_override="namespace:%s" % pod.namespace )
                        except Exception, e:
                            self._logger.error( "Error logging pod information for %s: %s" % (pod.name, str( e )) )



    def run( self ):
        # workaround a multithread initialization problem with time.strptime
        # see: http://code-trick.com/python-bug-attribute-error-_strptime/
        # we can ignore the result
        tm = time.strptime( "2016-08-29", "%Y-%m-%d" )

        if self.__container_checker:
            self.__container_checker.start()

        k8s_cache = self.__get_k8s_cache()

        try:
            # check to see if the user has manually specified a cluster name, and if so then
            # force enable 'Starbuck' features
            if self.__container_checker and self.__container_checker.k8s_cache.get_cluster_name() is not None:
                self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Cluster name detected, enabling k8s metric reporting and controller information" )
                self.__include_controller_info = True
                self.__report_k8s_metrics = self.__report_container_metrics

            if self.__report_k8s_metrics:

                runtime = None
                if k8s_cache:
                    runtime = k8s_cache.get_container_runtime()

                if runtime == 'docker':
                    self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )
                    self.__metric_fetcher = DockerMetricFetcher(self.__client, self.__docker_max_parallel_stats )

                k8s = KubernetesApi(k8s_api_url=self.__k8s_api_url)
                self.__kubelet_api = KubeletApi( k8s )
        except Exception, e:
            self._logger.error( "Error creating KubeletApi object. Kubernetes metrics will not be logged: %s" % str( e ) )
            self.__report_k8s_metrics = False


        global_log.info('kubernetes_monitor parameters: ignoring namespaces: %s, report_controllers %s, '
                        'report_metrics %s' % (','.join(self.__namespaces_to_ignore),
                                                         str(self.__include_controller_info),
                                                         str(self.__report_container_metrics)))
        ScalyrMonitor.run( self )

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        if self.__container_checker is not None:
            self.__container_checker.stop( wait_on_join, join_timeout )

        if self.__metric_fetcher is not None:
            self.__metric_fetcher.stop()

