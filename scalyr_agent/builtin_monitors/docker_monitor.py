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

define_config_option( __monitor__, 'docker_raw_logs',
                     'Optional (defaults to False). If True, the docker monitor will use the raw log files on disk to read logs.'
                     'The location of the raw log file is obtained by querying the path from the Docker API. '
                     'If false, the logs will be streamed over the Docker API.',
                     convert_to=bool,
                     default=False)

define_config_option( __monitor__, 'metrics_only',
                     'Optional (defaults to False). If true, the docker monitor will only log docker metrics and not any other information '
                     'about running containers.  If set to true, this value overrides the config item \'report_container_metrics\'\n',
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
                    only_running_containers=True, glob_list=None, include_log_path=False):
    """Gets a dict of running containers that maps container id to container name
    """
    if logger is None:
        logger = global_log

    result = {}
    try:
        filters = {"id": restrict_to_container} if restrict_to_container is not None else None
        response = client.containers(filters=filters, all=not only_running_containers)
        for container in response:
            cid = container['Id']

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
                    if include_log_path:
                        try:
                            info = client.inspect_container( cid )
                            log_path = info['LogPath'] if 'LogPath' in info else None
                        except Exception, e:
                          logger.error("Error inspecting container '%s'" % cid, limit_once_per_x_secs=300,limit_key="docker-api-inspect")

                    result[cid] = {'name': name, 'log_path': log_path }

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

    def __init__( self, config, logger, socket_file, docker_api_version, host_hostname, data_path, log_path ):

        self._config = config
        self._logger = logger

        self._use_raw_logs = config.get('docker_raw_logs')

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
        self.__checkpoints = {}

        self.__log_watcher = None
        self.__module = None
        self.__start_time = time.time()
        self.__thread = StoppableThread( target=self.check_containers, name="Container Checker" )

    def start( self ):
        self.__load_checkpoints()
        self.containers = _get_containers(self.__client, ignore_container=self.container_id, glob_list=self.__glob_list, include_log_path=self._use_raw_logs)

        # if querying the docker api fails, set the container list to empty
        if self.containers == None:
            self.containers = {}


        self.docker_logs = self.__get_docker_logs( self.containers )
        self.docker_loggers = []
        self.raw_logs = []

        #create and start the DockerLoggers
        self.__start_docker_logs( self.docker_logs )
        self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Initialization complete.  Starting docker monitor for Scalyr" )
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers
        if self._use_raw_logs:
            for logger in self.raw_logs:
                path = logger['log_config']['path']
                if self.__log_watcher:
                    self.__log_watcher.remove_log_path( self.__module.module_name, path )
                self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping %s" % (path) )
        else:
            for logger in self.docker_loggers:
                if self.__log_watcher:
                    self.__log_watcher.remove_log_path( self.__module.module_name, logger.log_path )
                logger.stop( wait_on_join, join_timeout )
                self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Stopping %s - %s" % (logger.name, logger.stream) )

        self.__update_checkpoints()

        self.docker_loggers = []
        self.raw_logs = []

    def check_containers( self, run_state ):

        while run_state.is_running():
            try:
                self.__update_checkpoints()

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Attempting to retrieve list of containers:' )
                running_containers = _get_containers(self.__client, ignore_container=self.container_id, glob_list=self.__glob_list, include_log_path=self._use_raw_logs)

                # if running_containers is None, that means querying the docker api failed.
                # rather than resetting the list of running containers to empty
                # continue using the previous list of containers
                if running_containers is None:
                    self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Failed to get list of containers')
                    running_containers = self.containers

                self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Found %d containers' % len(running_containers))
                #get the containers that have started since the last sample
                starting = {}

                for cid, info in running_containers.iteritems():
                    if cid not in self.containers:
                        self._logger.log(scalyr_logging.DEBUG_LEVEL_1, "Starting loggers for container '%s'" % info['name'] )
                        starting[cid] = info

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
                self.__start_loggers( starting )

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

    def __update_checkpoints( self ):
        """Update the checkpoints for when each docker logger logged a request, and save the checkpoints
        to file.
        """

        # checkpoints are only used for querying from the API, so ignore
        # them if we are using raw logs
        if not self._use_raw_logs:
            for logger in self.docker_loggers:
                last_request = logger.last_request()
                self.__checkpoints[logger.stream_name] = last_request

            # save to disk
            if self.__checkpoints:
                tmp_file = self.__checkpoint_file + '~'
                scalyr_util.atomic_write_dict_as_json_file( self.__checkpoint_file, tmp_file, self.__checkpoints )

    def __load_checkpoints( self ):
        try:
            checkpoints = scalyr_util.read_file_as_json( self.__checkpoint_file )
        except:
            self._logger.info( "No checkpoint file '%s' exists.\n\tAll logs will be read starting from their current end.", self.__checkpoint_file )
            checkpoints = {}

        if checkpoints:
            for name, last_request in checkpoints.iteritems():
                self.__checkpoints[name] = last_request

    def __stop_loggers( self, stopping ):
        """
        Stops any DockerLoggers in the 'stopping' dict
        @param: stopping - a dict of container ids => container names. Any running containers that have
        the same container-id as a key in the dict will be stopped.
        """
        if stopping:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Stopping all docker loggers')

            if self._use_raw_logs:
                for logger in self.raw_logs:
                    if logger['cid'] in stopping:
                        path = logger['log_config']['path']
                        if self.__log_watcher:
                            self.__log_watcher.schedule_log_path_for_removal( self.__module.module_name, path )

                self.raw_logs[:] = [l for l in self.raw_logs if l['cid'] not in stopping]
            else:
                for logger in self.docker_loggers:
                    if logger.cid in stopping:
                        logger.stop( wait_on_join=True, join_timeout=1 )
                        if self.__log_watcher:
                            self.__log_watcher.schedule_log_path_for_removal( self.__module.module_name, logger.log_path )

                self.docker_loggers[:] = [l for l in self.docker_loggers if l.cid not in stopping]

            self.docker_logs[:] = [l for l in self.docker_logs if l['cid'] not in stopping]

    def __start_loggers( self, starting ):
        """
        Starts a list of DockerLoggers
        @param: starting - a list of DockerLoggers to start
        """
        if starting:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_2, 'Starting all docker loggers')
            docker_logs = self.__get_docker_logs( starting )
            self.__start_docker_logs( docker_logs )
            self.docker_logs.extend( docker_logs )

    def __start_docker_logs( self, docker_logs ):
        for log in docker_logs:
            if self.__log_watcher:
                log['log_config'] = self.__log_watcher.add_log_config( self.__module, log['log_config'] )

            if self._use_raw_logs:
                self.raw_logs.append( log )
            else:
                last_request = self.__get_last_request_for_log( log['log_config']['path'] )
                self.docker_loggers.append( self.__create_docker_logger( log, last_request ) )

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

    def __get_docker_logs( self, containers ):
        """Returns a list of dicts containing the container id, stream, and a log_config
        for each container in the 'containers' param.
        """

        result = []

        attributes = None
        try:
            attributes = JsonObject( { "monitor": "agentDocker" } )
            if self.__host_hostname:
                attributes['serverHost'] = self.__host_hostname

        except Exception, e:
            self._logger.error( "Error setting monitor attribute in DockerMonitor" )
            raise

        prefix = self.__log_prefix + '-'

        for cid, info in containers.iteritems():
            container_attributes = attributes.copy()
            container_attributes['containerName'] = info['name']
            container_attributes['containerId'] = cid

            if self._use_raw_logs and 'log_path' in info and info['log_path']:
                log_config = self.__create_log_config( parser='docker', path=info['log_path'], attributes=container_attributes, parse_as_json=True )
                log_config['rename_logfile'] = '/docker/%s.log' % info['name']
                result.append( { 'cid': cid, 'stream': 'raw', 'log_config': log_config } )
            else:
                path =  prefix + info['name'] + '-stdout.log'
                log_config = self.__create_log_config( parser='dockerStdout', path=path, attributes=container_attributes )
                result.append( { 'cid': cid, 'stream': 'stdout', 'log_config': log_config } )

                path = prefix + info['name'] + '-stderr.log'
                log_config = self.__create_log_config( parser='dockerStderr', path=path, attributes=container_attributes.copy() )
                result.append( { 'cid': cid, 'stream': 'stderr', 'log_config': log_config } )

        return result

    def __create_docker_logger( self, log, last_request ):
        """Creates a new DockerLogger object, based on the parameters passed in in the 'log' param.

        @param: log - a dict consisting of:
                        cid - the container id
                        stream - whether this is the stdout or stderr stream
                        log_config - the log config used by the scalyr-agent for this log file
        """
        cid = log['cid']
        name = self.containers[cid]['name']
        stream = log['stream']
        stream_name = name + '-' + stream
        if stream_name in self.__checkpoints:
            checkpoint = self.__checkpoints[stream_name]
            if last_request < checkpoint:
                last_request = checkpoint

        logger = DockerLogger( self.__socket_file, cid, name, stream, log['log_config']['path'], self._config, last_request )
        logger.start()
        return logger



class DockerLogger( object ):
    """Abstraction for logging either stdout or stderr from a given container

    Logging is performed on a separate thread because each log is read from a continuous stream
    over the docker socket.
    """
    def __init__( self, socket_file, cid, name, stream, log_path, config, last_request=None, max_log_size=20*1024*1024, max_log_rotations=2 ):
        self.__socket_file = socket_file
        self.cid = cid
        self.name = name

        #stderr or stdout
        self.stream = stream
        self.log_path = log_path
        self.stream_name = name + "-" + stream

        self.__max_previous_lines = config.get( 'max_previous_lines' )
        self.__log_timestamps = True # Note: always log timestamps for now.  config.get( 'log_timestamps' )
        self.__docker_api_version = config.get( 'docker_api_version' )

        self.__last_request_lock = threading.Lock()

        self.__last_request = time.time()
        if last_request:
            self.__last_request = last_request

        self.__logger = logging.Logger( cid + '.' + stream )

        self.__log_handler = logging.handlers.RotatingFileHandler( filename = log_path, maxBytes = max_log_size, backupCount = max_log_rotations )
        formatter = logging.Formatter()
        self.__log_handler.setFormatter( formatter )
        self.__logger.addHandler( self.__log_handler )
        self.__logger.setLevel( logging.INFO )

        self.__client = None
        self.__logs = None

        self.__thread = StoppableThread( target=self.process_request, name="Docker monitor logging thread for %s" % (name + '.' + stream) )

    def start( self ):
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        if self.__client and self.__logs and self.__logs.response:
            sock = self.__client._get_raw_response_socket( self.__logs.response )
            if sock:
                sock.shutdown( socket.SHUT_RDWR )
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

    def last_request( self ):
        self.__last_request_lock.acquire()
        result = self.__last_request
        self.__last_request_lock.release()
        return result

    def process_request( self, run_state ):
        """This function makes a log request on the docker socket for a given container and continues
        to read from the socket until the connection is closed
        """
        try:
            # random delay to prevent all requests from starting at the same time
            delay = random.randint( 500, 5000 ) / 1000
            run_state.sleep_but_awaken_if_stopped( delay )

            self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Starting to retrieve logs for cid=%s' % str(self.cid))
            self.__client = DockerClient( base_url=('unix:/%s' % self.__socket_file ), version=self.__docker_api_version )

            epoch = datetime.datetime.utcfromtimestamp( 0 )
            while run_state.is_running():
                self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Attempting to retrieve logs for cid=%s' % str(self.cid))
                sout=False
                serr=False
                if self.stream == 'stdout':
                    sout = True
                else:
                    serr = True

                self.__logs = self.__client.logs(
                    container=self.cid,
                    stdout=sout,
                    stderr=serr,
                    stream=True,
                    timestamps=True,
                    tail=self.__max_previous_lines,
                    follow=True
                )

                # self.__logs is a generator so don't call len( self.__logs )
                self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Found log lines for cid=%s' % (str(self.cid)))
                try:
                    for line in self.__logs:
                        #split the docker timestamp from the frest of the line
                        dt, log_line = _split_datetime_from_line( line )
                        if not dt:
                            global_log.error( 'No timestamp found on line: \'%s\'', line )
                        else:
                            timestamp = scalyr_util.seconds_since_epoch( dt, epoch )

                            #see if we log the entire line including timestamps
                            if self.__log_timestamps:
                                log_line = line

                            #check to make sure timestamp is >= to the last request
                            #Note: we can safely read last_request here because we are the only writer
                            if timestamp >= self.__last_request:
                                self.__logger.info( log_line.strip() )

                                #but we need to lock for writing
                                self.__last_request_lock.acquire()
                                self.__last_request = timestamp
                                self.__last_request_lock.release()

                        if not run_state.is_running():
                            self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Exiting out of container log for cid=%s' % str(self.cid))
                            break
                except ProtocolError, e:
                    if run_state.is_running():
                        global_log.warning( "Stream closed due to protocol error: %s" % str( e ) )

                if run_state.is_running():
                    global_log.warning( "Log stream has been closed for '%s'.  Check docker.log on the host for possible errors.  Attempting to reconnect, some logs may be lost" % (self.name), limit_once_per_x_secs=300, limit_key='stream-closed-%s'%self.name )
                    delay = random.randint( 500, 3000 ) / 1000
                    run_state.sleep_but_awaken_if_stopped( delay )


            # we are shutting down, so update our last request to be slightly later than it's current
            # value to prevent duplicate logs when starting up again.
            self.__last_request_lock.acquire()

            #can't be any smaller than 0.01 because the time value is only saved to 2 decimal places
            #on disk
            self.__last_request += 0.01

            self.__last_request_lock.release()

        except Exception, e:
            global_log.warn('Unhandled exception in DockerLogger.process_request for %s:\n\t%s' % (self.name, str( e )))


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


class DockerMonitor( ScalyrMonitor ):
    """Monitor plugin for docker containers

    This plugin uses the Docker API to detect all containers running on the local host, retrieves metrics for each of
    them, and logs them to the Scalyr servers.

    It can also collect all log messages written to stdout and stderr by those containers, in conjunction with syslog.
    See the online documentation for more details.

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

        metrics_only = self._config.get('metrics_only')

        # always force reporting of container metrics if metrics_only is True
        if metrics_only:
            self.__report_container_metrics = True

        self.__container_checker = None
        if not metrics_only and self._config.get('log_mode') != 'syslog':
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

