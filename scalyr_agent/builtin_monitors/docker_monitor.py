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
from scalyr_agent import ScalyrMonitor, define_config_option
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
                     'Optional (defaults to scalyr-agent). Defines the name given to the container running the scalyr-agent\n'
                     'You should make sure to specify this same name when creating the docker container running scalyr\n'
                     'e.g. docker run --name scalyr-agent ...',
                     convert_to=str, default='scalyr-agent')

define_config_option( __monitor__, 'api_socket',
                     'Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket used to communicate with the docker API.\n'
                     'Note:  You need to map the host\'s /run/docker.sock to the same value as specified here, using the -v parameter, e.g.\n'
                     '\tdocker run -v /run/docker.sock:/var/scalyr/docker.sock ...',
                     convert_to=str, default='/var/scalyr/docker.sock')

define_config_option( __monitor__, 'docker_api_version',
                     'Optional (defaults to \'auto\'). The version of the Docker API to use\n',
                     convert_to=str, default='auto')

define_config_option( __monitor__, 'docker_log_prefix',
                     'Optional (defaults to docker). Prefix added to the start of all docker logs. ',
                     convert_to=str, default='docker')

define_config_option( __monitor__, 'max_previous_lines',
                     'Optional (defaults to 5000). The maximum number of lines to read backwards from the end of the stdout/stderr logs\n'
                     'when starting to log a containers stdout/stderr.',
                     convert_to=int, default=5000)

define_config_option( __monitor__, 'log_timestamps',
                     'Optional (defaults to False). If true, stdout/stderr logs will contain docker timestamps at the beginning of the line\n',
                     convert_to=bool, default=False)

define_metric( __monitor__, "docker.net.rx_bytes", "Total received bytes on the network interface", cumulative=True, unit="bytes" )
define_metric( __monitor__, "docker.net.rx_dropped", "Total receive packets dropped on the network interface", cumulative=True )
define_metric( __monitor__, "docker.net.rx_errors", "Total receive errors on the network interface", cumulative=True )
define_metric( __monitor__, "docker.net.rx_packets", "Total received packets on the network interface", cumulative=True )
define_metric( __monitor__, "docker.net.tx_bytes", "Total transmitted bytes on the network interface", cumulative=True, unit="bytes" )
define_metric( __monitor__, "docker.net.tx_dropped", "Total transmitted packets dropped on the network interface", cumulative=True )
define_metric( __monitor__, "docker.net.tx_errors", "Total transmission errors on the network interface", cumulative=True )
define_metric( __monitor__, "docker.net.tx_packets", "Total packets transmitted on the network intervace", cumulative=True )

define_metric( __monitor__, "docker.mem.stat.total_pgmajfault", "total_pgmajfault" )
define_metric( __monitor__, "docker.mem.stat.cache", "cache" )
define_metric( __monitor__, "docker.mem.stat.mapped_file", "mapped_file" )
define_metric( __monitor__, "docker.mem.stat.total_inactive_file", "total_inactive_file" )
define_metric( __monitor__, "docker.mem.stat.pgpgout", "pgpgout" )
define_metric( __monitor__, "docker.mem.stat.rss", "rss" )
define_metric( __monitor__, "docker.mem.stat.total_mapped_file", "total_mapped_file" )
define_metric( __monitor__, "docker.mem.stat.writeback", "writeback" )
define_metric( __monitor__, "docker.mem.stat.unevictable", "unevictable" )
define_metric( __monitor__, "docker.mem.stat.pgpgin", "pgpgin" )
define_metric( __monitor__, "docker.mem.stat.total_unevictable", "total_unevictable" )
define_metric( __monitor__, "docker.mem.stat.pgmajfault", "pgmajfault" )
define_metric( __monitor__, "docker.mem.stat.total_rss", "total_rss" )
define_metric( __monitor__, "docker.mem.stat.total_rss_huge", "total_rss_huge" )
define_metric( __monitor__, "docker.mem.stat.total_writeback", "total_writeback" )
define_metric( __monitor__, "docker.mem.stat.total_inactive_anon", "total_inactive_anon" )
define_metric( __monitor__, "docker.mem.stat.rss_huge", "rss_huge" )
define_metric( __monitor__, "docker.mem.stat.hierarchical_memory_limit", "hierarchical_memory_limit" )
define_metric( __monitor__, "docker.mem.stat.total_pgfault", "total_pgfault" )
define_metric( __monitor__, "docker.mem.stat.total_active_file", "total_active_file" )
define_metric( __monitor__, "docker.mem.stat.active_anon", "active_anon" )
define_metric( __monitor__, "docker.mem.stat.total_active_anon", "total_active_anon" )
define_metric( __monitor__, "docker.mem.stat.total_pgpgout", "total_pgpgout" )
define_metric( __monitor__, "docker.mem.stat.total_cache", "total_cache" )
define_metric( __monitor__, "docker.mem.stat.inactive_anon", "inactive_anon" )
define_metric( __monitor__, "docker.mem.stat.active_file", "active_file" )
define_metric( __monitor__, "docker.mem.stat.pgfault", "pgfault" )
define_metric( __monitor__, "docker.mem.stat.inactive_file", "inactive_file" )
define_metric( __monitor__, "docker.mem.stat.total_pgpgin", "total_pgpgin" )

define_metric( __monitor__, "docker.mem.max_usage", "max_usage" )
define_metric( __monitor__, "docker.mem.usage", "usage" )
define_metric( __monitor__, "docker.mem.fail_cnt", "fail_cnt" )
define_metric( __monitor__, "docker.mem.limit", "limit" )

define_metric( __monitor__, "docker.cpu.usage", "usage" )
define_metric( __monitor__, "docker.cpu.system_cpu_usage", "system_cpu_usage" )
define_metric( __monitor__, "docker.cpu.usage_in_usermode", "usage_in_usermode" )
define_metric( __monitor__, "docker.cpu.total_usage", "total_usage" )
define_metric( __monitor__, "docker.cpu.usage_in_kernelmode", "usage_in_kernelmode" )

define_metric( __monitor__, "docker.cpu.throttling.periods", "periods" )
define_metric( __monitor__, "docker.cpu.throttling.throttled_periods", "throttled_periods" )
define_metric( __monitor__, "docker.cpu.throttling.throttled_time", "throttled_time" )

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
        self.__log_timestamps = config.get( 'log_timestamps' )
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
        if self.__client and self.__logs:
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

        # random delay to prevent all requests from starting at the same time
        delay = random.randint( 500, 5000 ) / 1000
        run_state.sleep_but_awaken_if_stopped( delay )

        self.__client = DockerClient( base_url=('unix:/%s' % self.__socket_file ), version=self.__docker_api_version )

        epoch = datetime.datetime.utcfromtimestamp( 0 )
        while run_state.is_running():
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

            try:
                for line in self.__logs:
                    #split the docker timestamp from the frest of the line
                    dt, log_line = self.split_datetime_from_line( line )
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
                        break;
            except ProtocolError, e:
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

    def split_datetime_from_line( self, line ):
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




class DockerMonitor( ScalyrMonitor ):
    """Monitor plugin for docker containers

    This plugin accesses the Docker API to detect all containers running on a given host, and then logs messages from stdin and stdout
    to Scalyr servers.
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

    def __get_scalyr_container_id_and_name( self, client ):
        """Gets the container id of the scalyr-agent container
        If the config option container_name is empty, then it is assumed that the scalyr agent is running
        on the host and not in a container and None is returned.
        """
        result = None
        name = self._config.get( 'container_name' )

        if name:
            try:
                response = client.inspect_container( name )
                json = json_lib.parse( response )
                result = json['Id']
                name = json['Name'].lstrip( '/' )
            except:
                pass

            if not result:
                raise Exception( "Unable to find a matching container id for container '%s'.  Please make sure that a container named '%s' is running." % (name, name) )

        return result

    def __get_running_containers( self, client, currently_running ):
        """Gets a dict of running containers that maps container id to container name
        """

        result = {}
        try:
            response = client.containers( quiet=True )
            for container in response:
                cid = container['Id']
                if not cid == self.container_id:
                    if cid in currently_running:
                        # don't requery containers that we already know about
                        result[cid] = currently_running[cid]
                    else:
                        #query the container information
                        try:
                            info = client.inspect_container( cid )
                            result[cid] = { 'name' : info['Name'].lstrip( '/' ) }
                        except:
                            global_log.warning( "Error querying docker API for %s" % (cid ), limit_once_per_x_secs=300, limit_key='docker-api-query-%s' % cid )
        except: # container querying failed
            global_log.warning( "Error querying running containers", limit_once_per_x_secs=300, limit_key='docker-api-running-containers' )
            result = None

        return result

    def __create_log_config( self, parser, path, attributes ):

        return { 'parser': parser,
                 'path': path,
                 'attributes': attributes
               }

    def __get_docker_logs( self, containers ):
        result = []

        attributes = None
        try:
            attributes = JsonObject( { "monitor": "agentDocker" } )
            if self.__host_hostname:
                attributes['serverHost'] = self.__host_hostname

        except Exception, e:
            self._logger.error( "Error setting monitor attribute in DockerMonitor" )
            raise

        prefix = self._config.get( 'docker_log_prefix' ) + '-'

        for cid, name in containers.iteritems():
            path =  prefix + name + '-stdout.log'
            log_config = self.__create_log_config( parser='dockerStdout', path=path, attributes=attributes )
            result.append( { 'cid': cid, 'stream': 'stdout', 'log_config': log_config } )

            path = prefix + name + '-stderr.log'
            log_config = self.__create_log_config( parser='dockerStderr', path=path, attributes=attributes )
            result.append( { 'cid': cid, 'stream': 'stderr', 'log_config': log_config } )

        return result

    def _initialize( self ):
        data_path = ""
        self.__host_hostname = ""
        if self._global_config:
            data_path = self._global_config.agent_data_path

            if self._global_config.server_attributes:
                if 'serverHost' in self._global_config.server_attributes:
                    self.__host_hostname = self._global_config.server_attributes['serverHost']
                else:
                    self._logger.info( "no server host in server attributes" )
            else:
                self._logger.info( "no server attributes in global config" )

        self.__checkpoint_file = os.path.join( data_path, "docker-checkpoints.json" )

        self.__socket_file = self.__get_socket_file()
        self.__docker_api_version = self._config.get( 'docker_api_version' )
        self.__checkpoints = {}

        self.__client = DockerClient( base_url=('unix:/%s'%self.__socket_file), version=self.__docker_api_version )

        self.container_id, self.container_name = self.__get_scalyr_container_id_and_name( self.__client )
        self.__log_watcher = None
        self.__start_time = time.time()

    def set_log_watcher( self, log_watcher ):
        """Provides a log_watcher object that monitors can use to add/remove log files
        """
        self.__log_watcher = log_watcher

    def __create_docker_logger( self, log ):
        cid = log['cid']
        name = self.containers[cid]['name']
        stream = log['stream']
        stream_name = name + '-' + stream
        last_request = self.__start_time
        if stream_name in self.__checkpoints:
            last_request = self.__checkpoints[stream_name]

        logger = DockerLogger( self.__socket_file, cid, name, stream, log['log_config']['path'], self._config, last_request )
        logger.start()
        return logger

    def __stop_loggers( self, stopping ):
        if stopping:
            for logger in self.docker_loggers:
                if logger.cid in stopping:
                    logger.stop( wait_on_join=True, join_timeout=1 )
                    if self.__log_watcher:
                        self.__log_watcher.remove_log_path( self, logger.log_path )

            self.docker_loggers[:] = [l for l in self.docker_loggers if l.cid not in stopping]
            self.docker_logs[:] = [l for l in self.docker_logs if l['cid'] not in stopping]

    def __start_loggers( self, starting ):
        if starting:
            docker_logs = self.__get_docker_logs( starting )
            for log in docker_logs:
                if self.__log_watcher:
                    log['log_config'] = self.__log_watcher.add_log_config( self, log['log_config'] )
                self.docker_loggers.append( self.__create_docker_logger( log ) )

            self.docker_logs.extend( docker_logs )

    def __load_checkpoints( self ):
        try:
            checkpoints = scalyr_util.read_file_as_json( self.__checkpoint_file )
        except:
            self._logger.info( "No checkpoint file '%s' exists.\n\tAll logs will be read starting from their current end.", self.__checkpoint_file )
            checkpoints = {}

        if checkpoints:
            for name, last_request in checkpoints.iteritems():
                self.__checkpoints[name] = last_request

    def __update_checkpoints( self ):
        """Update the checkpoints for when each docker logger logged a request, and save the checkpoints
        to file.
        """

        for logger in self.docker_loggers:
            last_request = logger.last_request()
            self.__checkpoints[logger.stream_name] = last_request

        # save to disk
        if self.__checkpoints:
            tmp_file = self.__checkpoint_file + '~'
            scalyr_util.atomic_write_dict_as_json_file( self.__checkpoint_file, tmp_file, self.__checkpoints )

    def __build_metric_dict( self, prefix, names ):
        result = {}
        for name in names:
            result["%s%s"%(prefix, name)] = name
        return result

    def __log_metrics( self, container, metrics_to_emit, metrics, extra=None ):
        if not extra:
            extra = {}

        if container:
            extra['container'] = container

        for key, value in metrics_to_emit.iteritems():
            if value in metrics:
                self._logger.emit_value( key, metrics[value], extra )

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
                for usage in percpu:
                    extra = { 'container' : container, 'cpu' : count }
                    self._logger.emit_value( 'docker.cpu.usage', usage, extra )
                    count += 1
            self.__log_metrics( container, self.__cpu_usage_metrics, cpu_usage )

        if 'system_cpu_usage' in metrics:
            extra = { 'container' : container }
            self._logger.emit_value( 'docker.cpu.system_cpu_usage', metrics['system_cpu_usage'], extra )

        if 'throttling_data' in metrics:
            self.__log_metrics( container, self.__cpu_throttling_metrics, metrics['throttling_data'] )

    def __log_json_metrics( self, container, metrics ):

        for key, value in metrics.iteritems():
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
            result = self.__client.stats(
                container=container,
                stream=False
            )
            self.__log_json_metrics( container, result )
        except:
            self._logger.warning( "Error readings stats for '%s'" % (container), limit_once_per_x_secs=300, limit_key='api-stats-%s'%container )

    def __gather_metrics_from_api( self, containers ):

        if self.container_name:
            self.__gather_metrics_from_api_for_container( self.container_name )

        for cid, info in containers.iteritems():
            self.__gather_metrics_from_api_for_container( info['name'] )

    def gather_sample( self ):
        self.__update_checkpoints()

        running_containers = self.__get_running_containers( self.__client, self.containers )

        # if running_containers is None, that means querying the docker api failed.
        # rather than resetting the list of running containers to empty
        # continue using the previous list of containers
        if running_containers == None:
            running_containers = self.containers

        #get the containers that have started since the last sample
        starting = {}
        for cid, name in running_containers.iteritems():
            if cid not in self.containers:
                self._logger.info( "Starting logger for container '%s'" % name )
                starting[cid] = name

        #get the containers that have stopped
        stopping = {}
        for cid, name in self.containers.iteritems():
            if cid not in running_containers:
                self._logger.info( "Stopping logger for container '%s'" % name )
                stopping[cid] = name

        #stop the old loggers
        self.__stop_loggers( stopping )

        #update the list of running containers
        #do this before starting new ones, as starting up new ones
        #will access self.containers
        self.containers = running_containers

        #start the new ones
        self.__start_loggers( starting )

        # gather metrics
        # self.__gather_metrics_from_api( self.containers )


    def run( self ):
        self.__load_checkpoints()
        self.containers = self.__get_running_containers( self.__client, {} )

        # if querying the docker api fails, set the container list to empty
        if self.containers == None:
            self.containers = {}

        self.docker_logs = self.__get_docker_logs( self.containers )
        self.docker_loggers = []

        #create and start the DockerLoggers
        for log in self.docker_logs:
            if self.__log_watcher:
                log['log_config'] = self.__log_watcher.add_log_config( self, log['log_config'] )
            self.docker_loggers.append( self.__create_docker_logger( log ) )

        self._logger.info( "Initialization complete.  Starting docker monitor for Scalyr" )
        ScalyrMonitor.run( self )

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers
        for logger in self.docker_loggers:
            if self.__log_watcher:
                self.__log_watcher.remove_log_path( self, logger.log_path )
            logger.stop( wait_on_join, join_timeout )
            self._logger.info( "Stopping %s - %s" % (logger.name, logger.stream) )

        self.__update_checkpoints()

