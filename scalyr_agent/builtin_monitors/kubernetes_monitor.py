# Copyright 2014 Scalyr Inc.
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
# author:  Imron Alston <imron@imralsoftware.com>

__author__ = 'imron@imralsoftware.com'

import datetime
import docker
import fnmatch
import hashlib
import traceback
import logging
import os
import re
import random
import socket
import stat
import struct
import sys
import time
import threading
from scalyr_agent import ScalyrMonitor, define_config_option, define_metric
import scalyr_agent.util as scalyr_util
import scalyr_agent.json_lib as json_lib
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.monitor_utils.server_processors import LineRequestParser
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.server_processors import RequestStream
from scalyr_agent.monitor_utils.k8s import KubernetesApi

from scalyr_agent.util import StoppableThread

from scalyr_agent.util import RunState

from requests.packages.urllib3.exceptions import ProtocolError

global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.docker_monitor``',
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
                      'to Scalyr.', convert_to=bool, default=True)

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

def _get_containers(client, ignore_container=None, restrict_to_container=None, logger=None,
                    only_running_containers=True, glob_list=None, include_log_path=False, include_k8s_info=False):
    """Gets a dict of running containers that maps container id to container name
    """
    if logger is None:
        logger = global_log

    k8s_labels = {
        'pod_uid': 'io.kubernetes.pod.uid',
        'pod_name': 'io.kubernetes.pod.name',
        'pod_namespace': 'io.kubernetes.pod.namespace',
        'k8s_container_name': 'io.kubernetes.container.name'
    }

    result = {}
    try:
        filters = {"id": restrict_to_container} if restrict_to_container is not None else None
        response = client.containers(filters=filters, all=not only_running_containers)
        for container in response:
            cid = container['Id']
            short_cid = cid[:8]

            if ignore_container is not None and cid == ignore_container:
                continue

            if len( container['Names'] ) > 0:
                name = container['Names'][0].lstrip('/')

                add_container = True

                if glob_list:
                    add_container = False
                    for glob in glob_list:
                        if fnmatch.fnmatch( name, glob ):
                            add_container = True
                            break;

                if add_container:
                    log_path = None
                    k8s_info = None
                    status = None
                    if include_log_path or include_k8s_info:
                        try:
                            info = client.inspect_container( cid )
                            log_path = info['LogPath'] if include_log_path and 'LogPath' in info else None

                            if not only_running_containers:
                                status = info['State']['Status']

                            if include_k8s_info:
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
                                    logger.log( scalyr_logging.DEBUG_LEVEL_0, "Container Labels %s" % (json_lib.serialize(labels)), limit_once_per_x_secs=300,limit_key="docker-inspect-container-dump-%s" % short_cid)

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

class PodInfo( object ):
    """
        A collection class that stores label and other information about a kubernetes pod
    """
    def __init__( self, name='', namespace='', uid='', node_name='', labels={} ):

        self.name = name
        self.namespace = namespace
        self.uid = uid
        self.node_name = node_name
        self.labels = labels

        # generate a hash we can use to compare whether or not
        # any of the pod info has changed
        md5 = hashlib.md5()
        md5.update( name )
        md5.update( namespace )
        md5.update( uid )
        md5.update( node_name )

        # flatten the labels dict in to a single string
        flattened = []
        for k,v in labels.iteritems():
            flattened.append( k )
            flattened.append( v )
        md5.update( ''.join( flattened ) )

        self.digest = md5.digest()


class ContainerChecker( StoppableThread ):
    """
        Monitors containers to check when they start and stop running.
    """

    def __init__( self, config, logger, socket_file, docker_api_version, host_hostname, data_path, log_path ):

        self._config = config
        self._logger = logger

        self.__delay = self._config.get( 'container_check_interval' )
        self.__log_prefix = self._config.get( 'docker_log_prefix' )
        name = self._config.get( 'container_name' )

        self.__socket_file = socket_file
        self.__docker_api_version = docker_api_version
        self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )

        self.container_id = self.__get_scalyr_container_id( self.__client, name )

        self.__checkpoint_file = os.path.join( data_path, "docker-checkpoints.json" )
        self.__log_path = log_path

        self.__host_hostname = host_hostname

        self.__readback_buffer_size = self._config.get( 'readback_buffer_size' )

        self.__glob_list = config.get( 'container_globs' )

        self.containers = {}

        self.__k8s = KubernetesApi()
        self.__k8s_filter = None

        self.__log_watcher = None
        self.__module = None
        self.__start_time = time.time()
        self.__thread = StoppableThread( target=self.check_containers, name="Container Checker" )

    def start( self ):

        try:
            self.__k8s_filter = self._build_k8s_filter()

            # TODO set this to debug_level_1 after WW PoC
            self._logger.log( scalyr_logging.DEBUG_LEVEL_0, "k8s filter for pod '%s' is '%s'" % (self.__k8s.get_pod_name(), self.__k8s_filter) )

            self.containers = _get_containers(self.__client, ignore_container=self.container_id, glob_list=self.__glob_list, include_log_path=True, include_k8s_info=True)

            # if querying the docker api fails, set the container list to empty
            if self.containers == None:
                self.containers = {}

            self.raw_logs = []

            k8s_data = self.get_k8s_data()
            self.docker_logs = self.__get_docker_logs( self.containers, k8s_data )

            #create and start the DockerLoggers
            self.__start_docker_logs( self.docker_logs )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Initialization complete.  Starting docker monitor for Scalyr" )
            self.__thread.start()

        except Exception, e:
            global_log.warn( "Failed to start container checker %s\n%s" % (str(e), traceback.format_exc() ))


    def stop( self, wait_on_join=True, join_timeout=5 ):
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers

        for logger in self.raw_logs:
            path = logger['log_config']['path']
            if self.__log_watcher:
                self.__log_watcher.remove_log_path( self.__module, path )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping %s" % (path) )

        self.raw_logs = []

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

    def _process_pods( self, pods ):
        """
            Processes the JsonObject pods to retrieve the relevant
            information that we are going to upload to the server for each pod (see the PodInfo object),
            including the pod name, node name, any labels, and any containers that are
            running on that pod.

            @param pods: The JSON object returned as a response from quering all pods

            @return: a dict keyed by namespace, whose values are a dict of pods inside that namespace, keyed by pod name
        """

        # get all pods
        items = pods.get( 'items', [] )

        # iterate over all pods, getting PodInfo and storing it in the result
        # dict, hashed by namespace and pod name
        result = {}
        for pod in items:
            info = self._process_pod( pod )
            self._logger.log( scalyr_logging.DEBUG_LEVEL_3, "Processing pod: %s:%s" % (info.namespace, info.name) )

            if info.namespace not in result:
                result[info.namespace] = {}

            current = result[info.namespace]
            if info.name in current:
                self._logger.warning( "Duplicate pod '%s' found in namespace '%s', overwriting previous values" % (info.name, info.namespace),
                                      limit_once_per_x_secs=300, limit_key='duplicate-pod-%s' % info.uid )

            current[info.name] = info

        return result

    def _process_pod( self, pod ):
        """ Generate a PodInfo object from a JSON object
        @param pod: The JSON object returned as a response to querying
            a specific pod from the k8s API

        @return A PodInfo object
        """

        result = {}

        metadata = pod.get( 'metadata', {} )
        spec = pod.get( 'spec', {} )
        labels = metadata.get( 'labels', {} )

        pod_name = metadata.get( "name", '' )
        namespace = metadata.get( "namespace", '' )

        # create the PodInfo
        result = PodInfo( name=pod_name,
                          namespace=namespace,
                          uid=metadata.get( "uid", '' ),
                          node_name=spec.get( "nodeName", '' ),
                          labels=labels)
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
            pods = self.__k8s.query_pods( filter=self.__k8s_filter )
            result = self._process_pods( pods )
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

        while run_state.is_running():
            try:

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve k8s data' )
                k8s_data = self.get_k8s_data()

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )
                running_containers = _get_containers(self.__client, ignore_container=self.container_id, glob_list=self.__glob_list, include_log_path=True, include_k8s_info=True)

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
                        pod = k8s_data.get( pod_namespace, {} ).get( pod_name, None )

                        if not pod:
                            self._logger.warning( "No pod info for container %s.  pod: '%s/%s'" % (cid[:8], pod_namespace, pod_name),
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
                self.__start_loggers( starting, k8s_data )

                prev_digests = digests

                # update the log config for any changed containers
                if self.__log_watcher:
                    for logger in self.raw_logs:
                        if logger['cid'] in changed:
                            info = changed[logger['cid']]
                            new_config = self.__get_log_config_for_container( logger['cid'], info, k8s_data, base_attributes )
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


            for logger in self.raw_logs:
                if logger['cid'] in stopping:
                    path = logger['log_config']['path']
                    if self.__log_watcher:
                        self.__log_watcher.remove_log_path( self.__module, path )

            self.raw_logs[:] = [l for l in self.raw_logs if l['cid'] not in stopping]
            self.docker_logs[:] = [l for l in self.docker_logs if l['cid'] not in stopping]

    def __start_loggers( self, starting, k8s_data ):
        """
        Starts a list of DockerLoggers
        @param: starting - a list of DockerLoggers to start
        """
        if starting:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Starting all docker loggers')
            docker_logs = self.__get_docker_logs( starting, k8s_data )
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

    def __get_log_config_for_container( self, cid, info, k8s_data, base_attributes ):
        result = None

        container_attributes = base_attributes.copy()
        container_attributes['containerName'] = info['name']
        container_attributes['containerId'] = cid
        parser = 'docker'

        k8s_info = info.get( 'k8s_info', {} )

        if k8s_info:
            pod_name = k8s_info.get('pod_name', 'invalid_pod')
            pod_namespace = k8s_info.get('pod_namespace', 'invalid_namespace')
            self._logger.info( "got k8s info for container %s, '%s/%s'" % (cid[:8], pod_namespace, pod_name) )
            pod = k8s_data.get(pod_namespace, {}).get(pod_name, None)
            if pod:
                container_attributes['pod_name'] = pod.name
                container_attributes['namespace'] = pod.namespace
                container_attributes['pod_uid'] = pod.uid
                container_attributes['node_name'] = pod.node_name
                for label, value in pod.labels.iteritems():
                    container_attributes[label] = value

                if 'parser' in pod.labels:
                    parser = pod.labels['parser']
            else:
                self._logger.warning( "Couldn't map container '%s' to pod '%s/%s'. Logging limited metadata from docker container labels instead." % ( cid[:8], pod_namespace, pod_name ),
                                    limit_once_per_x_secs=300,
                                    limit_key='k8s-docker-mapping-%s' % cid)
                container_attributes['pod_name'] = pod_name
                container_attributes['pod_namespace'] = pod_namespace
                container_attributes['pod_uid'] = k8s_info.get('pod_uid', 'invalid_uid')
                container_attributes['k8s_container_name'] = k8s_info.get('k8s_container_name', 'invalid_container_name')
        else:
            self._logger.info( "no k8s info for container %s" % cid[:8] )

        if 'log_path' in info and info['log_path']:
            result = self.__create_log_config( parser=parser, path=info['log_path'], attributes=container_attributes, parse_as_json=True )
            result['rename_logfile'] = '/docker/%s.log' % info['name']

        return result


    def __get_docker_logs( self, containers, k8s_data ):
        """Returns a list of dicts containing the container id, stream, and a log_config
        for each container in the 'containers' param.
        """

        result = []

        attributes = self.__get_base_attributes()

        prefix = self.__log_prefix + '-'

        for cid, info in containers.iteritems():
            log_config = self.__get_log_config_for_container( cid, info, k8s_data, attributes )
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
    """Monitor plugin for kubernetes

    This plugin is based of the docker_monitor plugin, and uses the raw logs mode of the docker
    plugin to send kubernetes logs to Scalyr.  It also reads labels from the Kubernetes api and
    associates them with the appropriate logs.
    TODO:  Back fill the instructions here.
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

        self.__socket_file = self.__get_socket_file()
        self.__docker_api_version = self._config.get( 'docker_api_version' )

        self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )

        self.__glob_list = self._config.get( 'container_globs' )

        self.__report_container_metrics = self._config.get('report_container_metrics')
        self.__report_k8s_info = True

        self.__container_checker = None
        if self._config.get('log_mode') != 'syslog':
            self.__container_checker = ContainerChecker( self._config, self._logger, self.__socket_file, self.__docker_api_version, host_hostname, data_path, log_path )

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

    def __log_metrics( self, container, metrics_to_emit, metrics, extra=None ):
        if metrics is None:
            return

        for key, value in metrics_to_emit.iteritems():
            if value in metrics:
                # Note, we do a bit of a hack to pretend the monitor's name include the container's name.  We take this
                # approach because the Scalyr servers already have some special logic to collect monitor names and ids
                # to help auto generate dashboards.  So, we want a monitor name like `docker_monitor(foo_container)`
                # for each running container.
                self._logger.emit_value( key, metrics[value], extra, monitor_id_override=container )

    def __log_network_interface_metrics( self, container, metrics, interface=None ):
        extra = {}
        if interface:
            extra['interface'] = interface

        self.__log_metrics( container, self.__network_metrics, metrics, extra )

    def __log_memory_stats_metrics( self, container, metrics ):
        if 'stats' in metrics:
            self.__log_metrics( container, self.__mem_stat_metrics, metrics['stats'] )

        self.__log_metrics( container, self.__mem_metrics, metrics )

    def __log_cpu_stats_metrics( self, container, metrics ):
        if 'cpu_usage' in metrics:
            cpu_usage = metrics['cpu_usage']
            if 'percpu_usage' in cpu_usage:
                percpu = cpu_usage['percpu_usage']
                count = 1
                if percpu:
                    for usage in percpu:
                        extra = { 'cpu' : count }
                        self._logger.emit_value( 'docker.cpu.usage', usage, monitor_id_override=container )
                        count += 1
            self.__log_metrics( container, self.__cpu_usage_metrics, cpu_usage )

        if 'system_cpu_usage' in metrics:
            self._logger.emit_value( 'docker.cpu.system_cpu_usage', metrics['system_cpu_usage'],
                                     monitor_id_override=container )

        if 'throttling_data' in metrics:
            self.__log_metrics( container, self.__cpu_throttling_metrics, metrics['throttling_data'] )

    def __log_json_metrics( self, container, metrics ):
        for key, value in metrics.iteritems():
            if value is None:
                continue

            if key == 'networks':
                for interface, network_metrics in value.iteritems():
                    self.__log_network_interface_metrics( container, network_metrics, interface )
            elif key == 'network':
                self.__log_network_interface_metrics( container, value )
            elif key == 'memory_stats':
                self.__log_memory_stats_metrics( container, value )
            elif key == 'cpu_stats':
                self.__log_cpu_stats_metrics( container, value )

    def __gather_metrics_from_api_for_container( self, container ):
        try:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve metrics for cid=%s' % container)
            result = self.__client.stats(
                container=container,
                stream=False
            )
            if result is not None:
                self.__log_json_metrics( container, result )
        except Exception, e:
            self._logger.error( "Error readings stats for '%s': %s\n%s" % (container, str(e), traceback.format_exc()), limit_once_per_x_secs=300, limit_key='api-stats-%s'%container )

    def __gather_metrics_from_api( self, containers ):

        for cid, info in containers.iteritems():
            self.__gather_metrics_from_api_for_container( info['name'] )

    def gather_sample( self ):
        # gather metrics
        if self.__report_container_metrics:
            containers = _get_containers(self.__client, ignore_container=None, glob_list=self.__glob_list )
            self._logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve metrics for %d containers' % len(containers))
            self.__gather_metrics_from_api( containers )

        if self.__report_k8s_info:
            containers = _get_containers( self.__client, only_running_containers=False, include_k8s_info=True )
            for cid, info in containers.iteritems():
                try:
                    extra = info['k8s_info']
                    extra['status'] = info['status']
                    self._logger.emit_value( 'docker.container_name', info['name'], extra, monitor_id_override="namespace:%s" % extra['pod_namespace'] )
                except Exception, e:
                    self._logger.error( "Error logging container information for %s: %s" % (cid[:8], str( e )) )

            if self.__container_checker:
                namespaces = self.__container_checker.get_k8s_data()
                for namespace, pods in namespaces.iteritems():
                    for pod_name, pod in pods.iteritems():
                        try:
                            extra = { 'pod_uid': pod.uid,
                                      'pod_namespace': pod.namespace,
                                      'node_name': pod.node_name }
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

        ScalyrMonitor.run( self )

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        if self.__container_checker:
            self.__container_checker.stop( wait_on_join, join_timeout )

