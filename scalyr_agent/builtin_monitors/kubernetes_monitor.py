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
import traceback
import logging
import os
import re
import random
import socket
import stat
from string import Template
import struct
import sys
import time
import threading
from scalyr_agent import ScalyrMonitor, define_config_option, define_metric
import scalyr_agent.util as scalyr_util
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.monitor_utils.server_processors import LineRequestParser
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.server_processors import RequestStream
from scalyr_agent.monitor_utils.k8s import KubernetesApi, KubeletApi, KubeletApiException, KubernetesCache, PodInfo

from scalyr_agent.util import StoppableThread

from scalyr_agent.util import RunState

from requests.packages.urllib3.exceptions import ProtocolError

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
                     convert_to=int, default=5)

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

define_config_option( __monitor__, 'metrics_only',
                     'Optional (defaults to False). If true, the docker monitor will only log docker metrics and not any other information '
                     'about running containers.\n',
                     convert_to=bool, default=False)

define_config_option( __monitor__, 'container_globs',
                     'Optional (defaults to None). If true, a list of glob patterns for container names.  Only containers whose names '
                     'match one of the glob patterns will be monitored.',
                      default=None)

define_config_option( __monitor__, 'report_container_metrics',
                      'Optional (defaults to True). If true, metrics will be collected from the container and reported  '
                      'to Scalyr.  Note, metrics are only collected from those containers whose logs are being collected',
                      convert_to=bool, default=True)

define_config_option( __monitor__, 'report_k8s_metrics',
                      'Optional (defaults to True). If true and report_container_metrics is true, metrics will be '
                      'collected from the k8s and reported to Scalyr.  ', convert_to=bool, default=False)

define_config_option( __monitor__, 'k8s_ignore_namespaces',
                      'Optional (defaults to "kube-system"). A comma-delimited list of the namespaces whose pods\'s '
                      'logs should not be collected and sent to Scalyr.', convert_to=str, default="kube-system")

define_config_option( __monitor__, 'k8s_include_all_containers',
                      'Optional (defaults to True). If True, all containers in all pods will be monitored by the kubernetes monitor '
                      'unless they have an include: false or exclude: true annotation. '
                      'If false, only pods/containers with an include:true or exclude:false annotation '
                      'will be monitored. See documentation on annotations for further detail.', convert_to=bool, default=True)

define_config_option( __monitor__, 'k8s_use_v2_attributes',
                      'Optional (defaults to False). If True, will use v2 version of attribute names instead of '
                      'the names used with the original release of this monitor.  This is a breaking change so could '
                      'break searches / alerts if you rely on the old names', convert_to=bool, default=False)

define_config_option( __monitor__, 'k8s_use_v1_and_v2_attributes',
                      'Optional (defaults to False). If True, send attributes using both v1 and v2 versions of their'
                      'names.  This may be used to fix breakages when you relied on the v1 attribute names',
                      convert_to=bool, default=False)

define_config_option( __monitor__, 'k8s_cache_expiry_secs',
                     'Optional (defaults to 30). The amount of time to wait between fully updating the k8s cache from the k8s api. '
                     'Increase this value if you want less network traffic from querying the k8s api.  Decrease this value if you '
                     'want dynamic updates to annotation configuration values to be processed more quickly.',
                     convert_to=int, default=30)

define_config_option( __monitor__, 'k8s_max_cache_misses',
                     'Optional (defaults to 20). The maximum amount of single query k8s cache misses that can occur in `k8s_cache_miss_interval` '
                     'secs before performing a full update of the k8s cache',
                     convert_to=int, default=20)

define_config_option( __monitor__, 'k8s_cache_miss_interval',
                     'Optional (defaults to 10). The number of seconds that `k8s_max_cache_misses` cache misses can occur in before '
                     'performing a full update of the k8s cache',
                     convert_to=int, default=10)
define_config_option( __monitor__, 'k8s_parse_json',
                      'Optional (defaults to True). If True, the log files will be parsed as json before uploading to the server '
                      'to extract log and timestamp fields.  If False, the raw json will be uploaded to Scalyr.',
                      convert_to=bool, default=True)

define_config_option( __monitor__, 'verify_k8s_api_queries',
                      'Optional (defaults to True). If true, then the ssl connection for all queries to the k8s API will be verified using '
                      'the ca.crt certificate found in the service account directory. If false, no verification will be performed. '
                      'This is useful for older k8s clusters where certificate verification can fail.',
                      convert_to=bool, default=True)

define_config_option( __monitor__, 'gather_k8s_pod_info',
                      'Optional (defaults to False). If true, then every gather_sample interval, metrics will be collected '
                      'from the docker and k8s APIs showing all discovered containers and pods. This is mostly a debugging aid '
                      'and there are performance implications to always leaving this enabled', convert_to=bool, default=False)

define_config_option( __monitor__, 'include_daemonsets_as_deployments',
                      'Optional (defaults to True). If true, then the logs for Daemonsets will be uploaded to Scalyr but '
                      'will be called Deployments in the Scalyr Web UI.  This means they will be listed as a deployment and'
                      'will have the k8s-deployment label.  This is a temporary hack because the UI does not yet have '
                      'the ability to display Daemonsets.  In the future, it will be supported, but will break anyone who '
                      'relies on the k8s-deployment label.',
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
        return WrappedResponseGenerator( self, response, decode )

    def _stream_raw_result( self, response ):
        return WrappedRawGenerator( self, response )

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
                    k8s_include_by_default=True, k8s_namespaces_to_exclude=None, current_time=None):
    """Queries the Docker API and returns a dict of running containers that maps container id to container name, and other info
        @param client: A docker.Client object
        @param ignore_container: String, a single container id to exclude from the results (useful for ignoring the scalyr_agent container)
        @param restrict_to_container: String, a single continer id that will be the only returned result
        @param logger: scalyr_logging.Logger.  Allows the caller to write logging output to a specific logger.  If None the default agent.log
            logger is used.
        @param only_running_containers: Boolean.  If true, will only return currently running containers
        @param running_or_created_after: Unix timestamp.  If specified, the results will include any currently running containers *and* any
            dead containers that were created after the specified time.  Used to pick up short-lived containers.
        @param glob_list: String.  A glob string that limit results to containers whose container names match the glob
        @param include_log_path: Boolean.  If true include the path to the raw log file on disk as part of the extra info mapped to the container id.
        @param k8s_cache: KubernetesCache.  If not None, k8s information (if it exists) for the container will be added as part of the extra info mapped to the container id
        @param k8s_include_by_default: Boolean.  If True, then all k8s containers are included by default, unless an include/exclude annotation excludes them.
            If False, then all k8s containers are excluded by default, unless an include/exclude annotation includes them.
        @param k8s_namespaces_to_exclude: List  The of namespaces whose containers should be excluded.
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
                          logger.error("Error inspecting container '%s'" % cid, limit_once_per_x_secs=300,limit_key="docker-api-inspect")


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

class ContainerChecker( StoppableThread ):
    """
        Monitors containers to check when they start and stop running.
    """

    def __init__( self, config, logger, socket_file, docker_api_version, host_hostname, data_path, log_path,
                  include_all, include_deployment_info, include_daemonsets_as_deployments, namespaces_to_ignore ):

        self._config = config
        self._logger = logger

        self.__delay = self._config.get( 'container_check_interval' )
        self.__log_prefix = self._config.get( 'docker_log_prefix' )
        self.__name = self._config.get( 'container_name' )

        self.__use_v2_attributes = self._config.get('k8s_use_v2_attributes')
        self.__use_v1_and_v2_attributes = self._config.get('k8s_use_v1_and_v2_attributes')

        self.__parse_json = self._config.get( 'k8s_parse_json' )

        self.__socket_file = socket_file
        self.__docker_api_version = docker_api_version
        self.__client = None

        self.container_id = None

        self.__log_path = log_path

        self.__host_hostname = host_hostname

        self.__readback_buffer_size = self._config.get( 'readback_buffer_size' )

        self.__glob_list = config.get( 'container_globs' )

        # The namespace whose logs we should not collect.
        self.__namespaces_to_ignore = namespaces_to_ignore

        # This is currently an experimental feature.  Including deployment information for every event uploaded about
        # a pod (cluster name, deployment name, deployment labels)
        self.__include_deployment_info = include_deployment_info

        # This is currently an experimental feature, that uploads DaemonSet information as a 'Deployment'
        self.__include_daemonsets_as_deployments = include_daemonsets_as_deployments

        self.containers = {}
        self.__include_all = include_all

        self.__k8s = None

        self.__k8s_cache_expiry_secs = self._config.get( 'k8s_cache_expiry_secs' )
        self.__k8s_max_cache_misses = self._config.get( 'k8s_max_cache_misses' )
        self.__k8s_cache_miss_interval = self._config.get( 'k8s_cache_miss_interval' )

        self.__k8s_filter = None
        self.k8s_cache = None

        self.__log_watcher = None
        self.__module = None
        self.__start_time = time.time()
        self.__thread = StoppableThread( target=self.check_containers, name="Container Checker" )

    def start( self ):

        try:
            if self._config.get( 'verify_k8s_api_queries' ):
                self.__k8s = KubernetesApi()
            else:
                self.__k8s = KubernetesApi( ca_file=None )

            self.__k8s_filter = self._build_k8s_filter()
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "k8s filter for pod '%s' is '%s'" % (self.__k8s.get_pod_name(), self.__k8s_filter) )

            self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )

            self.container_id = self.__get_scalyr_container_id( self.__client, self.__name )

            # create the k8s cache
            self.k8s_cache = KubernetesCache( self.__k8s, self._logger,
                cache_expiry_secs=self.__k8s_cache_expiry_secs,
                max_cache_misses=self.__k8s_max_cache_misses,
                cache_miss_interval=self.__k8s_cache_miss_interval,
                filter=self.__k8s_filter )

            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )

            self.containers = _get_containers(self.__client, ignore_container=self.container_id,
                                              glob_list=self.__glob_list, include_log_path=True,
                                              k8s_cache=self.k8s_cache, k8s_include_by_default=self.__include_all,
                                              k8s_namespaces_to_exclude=self.__namespaces_to_ignore)

            # if querying the docker api fails, set the container list to empty
            if self.containers is None:
                self.containers = {}

            self.raw_logs = []

            self.docker_logs = self.__get_docker_logs( self.containers, self.k8s_cache )

            #create and start the DockerLoggers
            self.__start_docker_logs( self.docker_logs )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Initialization complete.  Starting k8s monitor for Scalyr" )
            self.__thread.start()

        except Exception, e:
            global_log.warn( "Failed to start container checker %s\n%s" % (str(e), traceback.format_exc() ))


    def stop( self, wait_on_join=True, join_timeout=5 ):
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers

        for logger in self.raw_logs:
            path = logger['log_config']['path']
            if self.__log_watcher:
                self.__log_watcher.remove_log_path( self.__module.module_name, path )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping %s" % (path) )

        self.raw_logs = []

    #@property
    #def cluster_name( self ):
    #    return self.__k8s.get_cluster_name()

    def _build_k8s_filter( self ):
        """Builds a fieldSelector filter to be used when querying pods the k8s api"""
        result = None
        try:
            pod_name = self.__k8s.get_pod_name()
            node_name = self.__k8s.get_node_name( pod_name )

            if node_name:
                result = 'spec.nodeName=%s' % node_name
            else:
                self._logger.warning( "Unable to get node name for pod '%s'.  This will have negative performance implications for clusters with a large number of pods.  Please consider setting the environment variable SCALYR_K8S_NODE_NAME to valueFrom:fieldRef:fieldPath:spec.nodeName in your yaml file" )
        except Exception, e:
            global_log.warn( "Failed to build k8s filter %s\n%s" % (str(e), traceback.format_exc() ))

        return result

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

        # store the digests from the previous iteration of the main loop to see
        # if any pod information has changed
        prev_digests = {}
        base_attributes = self.__get_base_attributes()
        previous_time = time.time()

        while run_state.is_running():
            try:

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )

                current_time = time.time()
                running_containers = _get_containers(
                    self.__client, ignore_container=self.container_id, running_or_created_after=previous_time,
                    glob_list=self.__glob_list, include_log_path=True, k8s_cache=self.k8s_cache,
                    k8s_include_by_default=self.__include_all, current_time=current_time,
                    k8s_namespaces_to_exclude=self.__namespaces_to_ignore)
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

    def __get_scalyr_container_id( self, client, name ):
        """Gets the container id of the scalyr-agent container
        If the config option container_name is empty, then it is assumed that the scalyr agent is running
        on the host and not in a container and None is returned.
        """
        result = None

        regex = None
        if name is not None:
            regex = re.compile( name )

        # get all the containers
        containers = client.containers()

        for container in containers:

            # see if we are checking on names
            if name is not None:
                # if so, loop over all container names for this container
                # Note: containers should only have one name, but the 'Names' field
                # is a list, so iterate over it just in case
                for cname in container['Names']:
                    cname = cname.lstrip( '/' )
                    # check if the name regex matches
                    m = regex.match( cname )
                    if m:
                        result = container['Id']
                        break
            # not checking container name, so check the Command instead to see if it's the agent
            else:
                if container['Command'].startswith( '/usr/sbin/scalyr-agent-2' ):
                    result = container['Id']

            if result:
                break

        if not result:
            # only raise an exception if we were looking for a specific name but couldn't find it
            if name is not None:
                raise Exception( "Unable to find a matching container id for container '%s'.  Please make sure that a "
                                 "container matching the regular expression '%s' is running." % (name, name) )

        return result

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

    def __create_log_config( self, parser, path, attributes, parse_as_json=False ):
        """Convenience function to create a log_config dict from the parameters"""

        return { 'parser': parser,
                 'path': path,
                 'parse_lines_as_json' : parse_as_json,
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

                # get the deployment information if any
                if pod.deployment_name is not None:
                    deployment = k8s_cache.deployment( pod.namespace, pod.deployment_name )
                    if deployment:
                        rename_vars['deployment_name'] = deployment.name
                        if self.__include_deployment_info:
                            container_attributes['_k8s_dn'] = deployment.name
                            container_attributes['_k8s_dl'] = deployment.flat_labels
                elif pod.daemonset_name is not None and self.__include_daemonsets_as_deployments:
                    daemonset = k8s_cache.daemonset( pod.namespace, pod.daemonset_name )
                    if daemonset:
                        rename_vars['deployment_name'] = daemonset.name
                        if self.__include_deployment_info:
                            container_attributes['_k8s_dn'] = daemonset.name
                            container_attributes['_k8s_dl'] = daemonset.flat_labels

                # get the cluster name
                cluster_name = k8s_cache.get_cluster_name()
                if self.__include_deployment_info and cluster_name is not None:
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
            result = self.__create_log_config( parser=parser, path=info['log_path'], attributes=container_attributes, parse_as_json=self.__parse_json )
            result['rename_logfile'] = '/docker/%s.log' % info['name']
            # This is for a hack to prevent the original log file name from being added to the attributes.
            if self.__use_v2_attributes and not self.__use_v1_and_v2_attributes:
                result['rename_no_original'] = True

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

class ContainerIdResolver():
    """Abstraction that can be used to look up Docker container names based on their id.

    This has a caching layer built in to minimize lookups to actual Docker and make this as efficient as possible.

    This abstraction is thread-safe.
    """
    def __init__(self, docker_api_socket, docker_api_version, logger, cache_expiration_secs=300, cache_clean_secs=5):
        """
        Initializes one instance.

        @param docker_api_socket: The path to the UNIX socket exporting the Docker API by the daemon.
        @param docker_api_version: The API version to use, typically 'auto'.
        @param cache_expiration_secs: The number of seconds to cache a mapping from container id to container name.  If
            the mapping is not used for this number of seconds, the mapping will be evicted.  (The actual eviction
            is performed lazily).
        @param cache_clean_secs:  The number of seconds between sweeps to clean the cache.
        @param logger: The logger to use.  This MUST be supplied.
        @type docker_api_socket: str
        @type docker_api_version: str
        @type cache_expiration_secs: double
        @type cache_clean_secs: double
        @type logger: Logger
        """
        # Guards all variables except for __logger and __docker_client.
        self.__lock = threading.Lock()
        self.__cache = dict()
        # The walltime of when the cache was last cleaned.
        self.__last_cache_clean = time.time()
        self.__cache_expiration_secs = cache_expiration_secs
        self.__cache_clean_secs = cache_clean_secs
        self.__docker_client = docker.Client(base_url=('unix:/%s' % docker_api_socket), version=docker_api_version)
        # The set of container ids that have not been used since the last cleaning.  These are eviction candidates.
        self.__untouched_ids = dict()
        self.__logger = logger

    def lookup(self, container_id):
        """Looks up the container name for the specified container id.

        This does check the local cache first.

        @param container_id: The container id
        @type container_id: str
        @return:  The container name or None if the container id could not be resolved, or if there was an error
            accessing Docker.
        @rtype: str or None
        """
        try:
            #self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Looking up cid="%s"', container_id)
            current_time = time.time()

            self.__lock.acquire()
            try:
                self._clean_cache_if_necessary(current_time)

                # Check cache first and mark if it as recently used if found.
                if container_id in self.__cache:
                    entry = self.__cache[container_id]
                    self._touch(entry, current_time)
                    #self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Cache hit for cid="%s" -> "%s"', container_id,
                                      #entry.container_name)
                    return entry.container_name
            finally:
                self.__lock.release()

            container_name = self._fetch_id_from_docker(container_id)

            if container_name is not None:
                #self.__logger.log(scalyr_logging.DEBUG_LEVEL_1, 'Docker resolved id for cid="%s" -> "%s"', container_id,
                #                  container_name)

                self._insert_entry(container_id, container_name, current_time)
                return container_name

            #self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Docker could not resolve id="%s"', container_id)

        except Exception, e:
            self.__logger.error('Error seen while attempting resolving docker cid="%s"', container_id)

        return None

    def _clean_cache_if_necessary(self, current_time):
        """Cleans the cache if it has been too long since the last cleaning.

        You must be holding self.__lock.

        @param current_time:  The current walltime.
        @type current_time: double
        """
        if self.__last_cache_clean + self.__cache_clean_secs > current_time:
            return

        #self.__logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Cleaning cid cache. Before clean=%d:%d', len(self.__cache),
        #                  len(self.__untouched_ids))

        self.__last_cache_clean = current_time
        # The last access time that will trigger expiration.
        expire_threshold = current_time - self.__cache_expiration_secs

        # For efficiency, just examine the ids that haven't been used since the last cleaning.
        for key in self.__untouched_ids:
            if self.__cache[key].last_access_time < expire_threshold:
                del self.__cache[key]

        # Reset the untouched_ids to contain all of the ids.
        self.__untouched_ids = dict()
        for key in self.__cache:
            self.__untouched_ids[key] = True

        #self.__logger.log(scalyr_logging.DEBUG_LEVEL_2, 'After clean=%d:%d', len(self.__cache),
        #                  len(self.__untouched_ids))

    def _touch(self, cache_entry, last_access_time):
        """Mark the specified cache entry as being recently used.

        @param cache_entry: The entry
        @param last_access_time: The time it was accessed.
        @type cache_entry: ContainerIdResolver.Entry
        @type last_access_time: double
        """
        cid = cache_entry.container_id
        if cid in self.__untouched_ids:
            del self.__untouched_ids[cid]
        cache_entry.touch(last_access_time)

    def _fetch_id_from_docker(self, container_id):
        """Fetch the container name for the specified container using the Docker API.

        @param container_id: The id of the container.
        @type container_id: str
        @return: The container name or None if it was either not found or if there was an error.
        @rtype: str or None
        """
        matches = _get_containers(self.__docker_client, restrict_to_container=container_id,
                                  logger=self.__logger, only_running_containers=False)
        if len(matches) == 0:
            #self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'No matches found in docker for cid="%s"', container_id)
            return None

        if len(matches) > 1:
            self.__logger.warning("Container id matches %d containers for id='%s'." % (len(matches), container_id),
                                  limit_once_per_x_secs=300,
                                  limit_key='docker_container_id_more_than_one')
            return None

        # Note, the cid used as the key for the returned matches is the long container id, not the short one that
        # we were passed in as `container_id`.
        return matches[matches.keys()[0]]['name']

    def _insert_entry(self, container_id, container_name, last_access_time):
        """Inserts a new cache entry mapping the specified id to the container name.

        @param container_id: The id of the container.
        @param container_name: The name of the container.
        @param last_access_time: The time it this entry was last used.
        @type container_id: str
        @type container_name: str
        @type last_access_time: double
        """
        self.__lock.acquire()
        try:
            self.__cache[container_id] = ContainerIdResolver.Entry(container_id, container_name, last_access_time)
        finally:
            self.__lock.release()

    class Entry():
        """Helper abstraction representing a single cache entry mapping a container id to its name.
        """
        def __init__(self, container_id, container_name, last_access_time):
            """
            @param container_id: The id of the container.
            @param container_name: The name of the container.
            @param last_access_time: The time the entry was last used.
            @type container_id: str
            @type container_name: str
            @type last_access_time: double
            """
            self.__container_id = container_id
            self.__container_name = container_name
            self.__last_access_time = last_access_time

        @property
        def container_id(self):
            """
            @return:  The id of the container.
            @rtype: str
            """
            return self.__container_id

        @property
        def container_name(self):
            """
            @return:  The name of the container.
            @rtype: str
            """
            return self.__container_name

        @property
        def last_access_time(self):
            """
            @return:  The last time this entry was used, in seconds past epoch.
            @rtype: double
            """
            return self.__last_access_time

        def touch(self, access_time):
            """Updates the last access time for this entry.

            @param access_time: The time of the access.
            @type access_time: double
            """
            self.__last_access_time = access_time


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
    pods/containers you don't want.  You can also set a value in agent.json
    `k8s_include_all_containers: false`, in which case all containers are excluded by default and
    have to be manually included.

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

        # The namespace whose logs we should not collect.
        self.__namespaces_to_ignore = []
        for x in self._config.get('k8s_ignore_namespaces').split():
            self.__namespaces_to_ignore.append(x.strip())

        self.__socket_file = self.__get_socket_file()
        self.__docker_api_version = self._config.get( 'docker_api_version' )

        self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )

        self.__glob_list = self._config.get( 'container_globs' )
        self.__include_all = self._config.get( 'k8s_include_all_containers' )

        self.__report_container_metrics = self._config.get('report_container_metrics')
        self.__report_k8s_metrics = self._config.get('report_k8s_metrics') and self.__report_container_metrics
        # Object for talking to the kubelet server running on this localhost.  This is used to gather metrics only
        # available via the kubelet.
        self.__kubelet_api = None
        self.__gather_k8s_pod_info = self._config.get('gather_k8s_pod_info')

        # Including deployment information for every event uploaded about  a pod (cluster name, deployment name,
        # deployment labels)
        self.__include_deployment_info = self._config.get('include_deployment_info', convert_to=bool, default=False)

        # Treat DaemonSets as Deployments
        self.__include_daemonsets_as_deployments = self._config.get('include_daemonsets_as_deployments')

        self.__container_checker = None
        if self._config.get('log_mode') != 'syslog':
            self.__container_checker = ContainerChecker( self._config, self._logger, self.__socket_file,
                                                         self.__docker_api_version, host_hostname, data_path, log_path,
                                                         self.__include_all, self.__include_deployment_info, self.__include_daemonsets_as_deployments,
                                                         self.__namespaces_to_ignore)

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
        try:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve metrics for cid=%s' % container)
            result = self.__client.stats(
                container=container,
                stream=False
            )
            if result is not None:
                self.__log_json_metrics( container, result, k8s_extra )
        except Exception, e:
            self._logger.error( "Error readings stats for '%s': %s\n%s" % (container, str(e), traceback.format_exc()), limit_once_per_x_secs=300, limit_key='api-stats-%s'%container )

    def __build_k8s_deployment_info( self, k8s_cache, pod ):
        """
            Builds a dict containing information about the deployment settings for a given pod

            @param: k8s_cache - a k8s cache object for query deployment information
            @param: pod - a PodInfo object containing basic information (namespace/name) about the pod to query

            @return: a dict containing the deployment name and deployment labels for the deployment running
                     the specified pod, or an empty dict if the pod is not part of a deployment
        """
        k8s_extra = {}
        if k8s_cache and pod is not None:
            if pod.deployment_name is not None:
                deployment = k8s_cache.deployment( pod.namespace, pod.deployment_name )
                if deployment:
                    k8s_extra = {
                        'k8s-deployment': deployment.name
                    }
            elif pod.daemonset_name is not None and self.__include_daemonsets_as_deployments:
                daemonset = k8s_cache.daemonset( pod.namespace, pod.daemonset_name )
                if daemonset:
                    k8s_extra = {
                        'k8s-deployment': daemonset.name
                    }
        return k8s_extra

    def __get_k8s_deployment_info( self, container, k8s_cache ):
        """
            Gets information about the kubernetes deployment of a given container
            @param: container - a dict containing information about a container, returned by _get_containers
            @param: k8s_cache - a cache for querying the k8s api
        """
        k8s_info = container.get( 'k8s_info', {} )
        pod = k8s_info.get( 'pod_info', None )
        if pod is None:
            return None
        return self.__build_k8s_deployment_info( k8s_cache, pod )


    def __get_cluster_info( self, cluster_name ):
        """ returns a dict of values about the cluster """
        cluster_info = {}
        if self.__include_deployment_info and cluster_name is not None:
            cluster_info['k8s-cluster'] = cluster_name

        return cluster_info

    def __gather_metrics_from_api( self, containers, k8s_cache, cluster_name ):

        cluster_info = self.__get_cluster_info( cluster_name )

        for cid, info in containers.iteritems():
            k8s_extra = {}
            if self.__include_deployment_info:
                k8s_extra = self.__get_k8s_deployment_info( info, k8s_cache )
                if k8s_extra is not None:
                    k8s_extra.update( cluster_info )
                    k8s_extra.update({'pod_uid': info['name']})
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

    def __gather_k8s_metrics_from_kubelet( self, containers, kubelet_api, k8s_cache, cluster_name ):
        """
            Gathers k8s metrics from a response to a stats query of the Kubelet API

            @param: containers - a dict returned by _get_containers with info for all containers we are interested in
            @param: kubelet_api - a KubeletApi object for querying the KubeletApi
            @param: k8s_cache - a KubernetesCache object for query items from the k8s cache
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
                deployment_info = {}
                if self.__include_deployment_info:
                    deployment_info = self.__build_k8s_deployment_info( k8s_cache, info )
                    deployment_info.update( cluster_info )
                self.__gather_k8s_metrics_for_pod( pod, info, deployment_info )

        except KubeletApiException, e:
            self._logger.warning( "Error querying kubelet API: %s" % str( e ),
                                  limit_once_per_x_secs=300,
                                  limit_key='kubelet-api-query' )

    def gather_sample( self ):
        k8s_cache = None
        if self.__container_checker:
            k8s_cache = self.__container_checker.k8s_cache

        cluster_name = None
        if k8s_cache is not None:
            cluster_name = k8s_cache.get_cluster_name()

        # gather metrics
        containers = None
        if self.__report_container_metrics:
            containers = _get_containers(self.__client, ignore_container=None, glob_list=self.__glob_list,
                                         k8s_cache=k8s_cache, k8s_include_by_default=self.__include_all,
                                         k8s_namespaces_to_exclude=self.__namespaces_to_ignore)
        try:
            if containers:
                if self.__report_container_metrics:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve metrics for %d containers' % len(containers))
                    self.__gather_metrics_from_api( containers, k8s_cache, cluster_name )

                if self.__report_k8s_metrics:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve k8s metrics %d' % len(containers))
                    self.__gather_k8s_metrics_from_kubelet( containers, self.__kubelet_api, k8s_cache, cluster_name )
        except Exception, e:
            self._logger.exception( "Unexpected error logging metrics: %s" %( str(e) ) )

        if self.__gather_k8s_pod_info:

            cluster_info = self.__get_cluster_info( cluster_name )

            containers = _get_containers( self.__client, only_running_containers=False, k8s_cache=k8s_cache,
                                          k8s_include_by_default=self.__include_all,
                                          k8s_namespaces_to_exclude=self.__namespaces_to_ignore)
            for cid, info in containers.iteritems():
                try:
                    extra = info.get( 'k8s_info', {} )
                    extra['status'] = info.get('status', 'unknown')
                    if self.__include_deployment_info:
                        deployment = self.__get_k8s_deployment_info( info, k8s_cache )
                        extra.update( deployment )
                        extra.update( cluster_info )

                    namespace = extra.get( 'pod_namespace', 'invalid-namespace' )
                    self._logger.emit_value( 'docker.container_name', info['name'], extra, monitor_id_override="namespace:%s" % namespace )
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

                            if self.__include_deployment_info:
                                deployment_info = self.__build_k8s_deployment_info( k8s_cache, pod )
                                if deployment_info:
                                    extra.update( deployment_info )
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
            if self._global_config:
                server_attributes = self._global_config.server_attributes
                # cluster_name = self.__container_checker.cluster_name
                # if cluster_name is not None and '_k8s_cn' not in server_attributes:
                #    # commenting this out for now because it causing the config to be continually reloaded
                #    # server_attributes['_k8s_cn'] = cluster_name
                #    pass

        try:
            if self.__report_k8s_metrics:
                k8s = KubernetesApi()
                self.__kubelet_api = KubeletApi( k8s )
        except Exception, e:
            self._logger.error( "Error creating KubeletApi object. Kubernetes metrics will not be logged: %s" % str( e ) )
            self.__report_k8s_metrics = False

        global_log.info('kubernetes_monitor parameters: ignoring namespaces: %s, report_deployments %s, '
                        'report_daemonsets %s, report_metrics %s' % (','.join(self.__namespaces_to_ignore),
                                                                     str(self.__include_deployment_info),
                                                                     str(self.__include_daemonsets_as_deployments),
                                                                     str(self.__report_container_metrics)))
        ScalyrMonitor.run( self )

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        if self.__container_checker:
            self.__container_checker.stop( wait_on_join, join_timeout )

