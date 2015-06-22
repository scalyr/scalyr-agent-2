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

import logging
import os
import re
import socket
import stat
import time
import threading
from scalyr_agent import ScalyrMonitor, define_config_option
import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.monitor_utils.server_processors import LineRequestParser
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.server_processors import RequestStream

from scalyr_agent.util import StoppableThread
from scalyr_agent.util import RunState


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

define_config_option( __monitor__, 'docker_log_prefix',
                     'Optional (defaults to docker). Prefix added to the start of all docker logs. ',
                     convert_to=str, default='docker')

class DockerRequest( object ):

    def __init__( self, sock_file, max_request_size=64*1024 ):
        self.__socket = socket.socket( socket.AF_UNIX, socket.SOCK_STREAM )
        self.__socket.connect( sock_file )
        self.__line_request = LineRequestParser( max_request_size, eof_as_eol=True )
        self.__request_stream = RequestStream( self.__socket, self.__line_request.parse_request, max_request_size, max_request_size )
        self.__headers = []

    def get( self, path ):
        endpoint = "GET %s HTTP/1.0\r\n\r\n" % path
        self.__socket.sendall( endpoint )
        self.__read_headers()
        return self

    def response_body( self ):
        
        result = ""
        while not self.__request_stream.at_end():
            line = self.__request_stream.read_request()
            if line != None:
                result += line
            
        return result

    def readline( self ):
        #Make sure the headers have been read - this might not be the case for some queries
        #even if __read_headers() has already been called
        if len( self.__headers ) == 0:
            self.__read_headers()
            return None

        return self.__request_stream.read_request()
        
    def __read_headers( self ):
        """reads HTTP headers from the request stream, leaving the stream at the first line of data"""
        self.response_code = 400
        self.response_message = "Bad request"

        #first line is response code
        line = self.__request_stream.read_request()
        if not line:
            return

        match = re.match( '^(\S+) (\d+) (.*)$', line.strip() )
        if not match:
            return

        if match.group(1).startswith( 'HTTP' ):
            self.response_code = int( match.group(2) )
            self.response_message = match.group(3)
            self.__headers = []
            while not self.__request_stream.at_end():
                line = self.__request_stream.read_request()
                if line == None:
                    break
                else:
                    cur_line = line.strip()
                    if len( cur_line ) == 0:
                        break
                    else:
                        self.__headers.append( cur_line )

class DockerLogger( object ):
    def __init__( self, socket_file, cid, name, stream, log_path, max_log_size=20*1024*1024, max_log_rotations=2 ):
        self.__socket_file = socket_file
        self.cid = cid
        self.name = name
        self.stream = stream
        self.__log_path = log_path

        self.__logger = logging.Logger( cid + '.' + stream )

        self.__log_handler = logging.handlers.RotatingFileHandler( filename = log_path, maxBytes = max_log_size, backupCount = max_log_rotations )
        formatter = logging.Formatter()
        self.__log_handler.setFormatter( formatter )
        self.__logger.addHandler( self.__log_handler )
        self.__logger.setLevel( logging.INFO )

        self.__thread = StoppableThread( target=self.process_request, name="Docker monitor logging thread for %s" % (name + '.' + stream) )

    def start( self ):
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )

    def process_request( self, run_state ):
        request = DockerRequest( self.__socket_file )
        request.get( '/containers/%s/logs?%s=1&follow=1&tail=0' % (self.cid, self.stream) )
        while run_state.is_running():
            line = request.readline()
            while line:
                self.__logger.info( line.strip() )
                line = request.readline()
            time.sleep( 0.1 )

        

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

    def __get_scalyr_container_id( self, socket_file ):
        """Gets the container id of the scalyr-agent container
        If the config option container_name is empty, then it is assumed that the scalyr agent is running
        on the host and not in a container and None is returned.
        """
        result = None
        name = self._config.get( 'container_name' )

        if name:
            request = DockerRequest( socket_file ).get( "/containers/%s/json" % name )

            if request.response_code == 200:
                json = json_lib.parse( request.response_body() )
                result = json['Id']

            if not result:
                raise Exception( "Unabled to find a matching container id for container '%s'.  Please make sure that a container named '%s' is running." % (name, name) )

        return result

    def __get_running_containers( self, socket_file ):
        """Gets a dict of running containers that maps container id to container name
        """
        request = DockerRequest( socket_file ).get( "/containers/json" )

        result = {}
        if request.response_code == 200:
            json = json_lib.parse( request.response_body() )
            for container in json:
                cid = container['Id']
                if not cid == self.container_id:
                    try:
                        containerRequest = DockerRequest( socket_file ).get( "/containers/%s/json" % cid )
                        if containerRequest.response_code == 200:
                            body = containerRequest.response_body()
                            containerJson = json_lib.parse( body )

                            result[cid] = containerJson['Name'].lstrip( '/' )
                    except:
                        result[cid] = cid
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
        except Exception, e:
            self._logger.error( "Error setting monitor attribute in DockerMonitor" )
            raise

        prefix = self._config.get( 'docker_log_prefix' ) + '-'

        for cid, name in containers.iteritems():
            path =  prefix + name + '-stdout.log'
            if not os.path.isabs( path ):
                path = os.path.join( self.__base_path, path )
            log_config = self.__create_log_config( parser='dockerStdout', path=path, attributes=attributes )
            result.append( { 'cid': cid, 'stream': 'stdout', 'log_config': log_config } )

            path = prefix + name + '-stderr.log'
            if not os.path.isabs( path ):
                path = os.path.join( self.__base_path, path )
            log_config = self.__create_log_config( parser='dockerStderr', path=path, attributes=attributes )
            result.append( { 'cid': cid, 'stream': 'stderr', 'log_config': log_config } )

        return result

    def _initialize( self ):

        self.__socket_file = self.__get_socket_file()
        self.container_id = self.__get_scalyr_container_id( self.__socket_file )

        self.__base_path = ""

        #this lock governs the public list of additional logs
        self.__lock = threading.Lock()
        self.__additional_logs = []
        self.__additional_logs_changed = True


    def __create_docker_logger( self, log ):
        cid = log['cid']
        name = self.containers[cid]
        stream = log['stream']
        logger = DockerLogger( self.__socket_file, cid, name, stream, log['log_config']['path'] )
        logger.start()
        return logger

    def __stop_loggers( self, stopping ):
        if stopping:
            for logger in self.docker_loggers:
                if logger.cid in stopping:
                    logger.stop( False, None )

            self.docker_loggers = [l for l in self.docker_loggers if l.cid not in stopping]
            self.docker_logs = [l for l in self.docker_logs if l['cid'] not in stopping]

    def __start_loggers( self, starting ):
        if starting:
            docker_logs = self.__get_docker_logs( starting )
            for log in docker_logs:
                self.docker_loggers.append( self.__create_docker_logger( log ) )

            self.docker_logs.extend( docker_logs )

    def __update_additional_logs( self, docker_logs ):
        self.__lock.acquire()
        self.__additional_logs = []
        for log in self.docker_logs:
            self.__additional_logs.append( log['log_config'] )
        self.__additional_logs_changed = True
        self._logger.info( "logs have changed %s" % str( self ) )
        self.__lock.release()

    def set_additional_log_path( self, path ):
        """Sets a path to write any additional logs that are created by the plugin
        """
        self.__base_path = path

    def additional_logs_have_changed( self ):
        return self.__additional_logs_changed

    def get_additional_logs( self ):
        logs = []
        self.__lock.acquire()
        logs.extend( self.__additional_logs )
        self.__additional_logs_changed = False
        self._logger.info( "logs have reset" )
        self.__lock.release()
        return logs

    def gather_sample( self ):
        running_containers = self.__get_running_containers( self.__socket_file )

        update_logs = False

        #get the containers that have started since the last sample
        starting = {}
        for cid, name in running_containers.iteritems():
            if cid not in self.containers:
                update_logs = True
                self._logger.info( "Starting logger for container '%s'" % name )
                starting[cid] = name

        #get the containers that have stopped
        stopping = {}
        for cid, name in self.containers.iteritems():
            if cid not in running_containers:
                update_logs = True
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

        #update list of log files
        if update_logs:
            self.__update_additional_logs( self.containers )

    def run( self ):
        self.containers = self.__get_running_containers( self.__socket_file )
        self.docker_logs = self.__get_docker_logs( self.containers )
        self.docker_loggers = []

        #create and start the DockerLoggers
        for log in self.docker_logs:
            self.docker_loggers.append( self.__create_docker_logger( log ) )

        self.__update_additional_logs( self.containers )

        self._logger.info( "Initialization complete.  Starting docker monitor for Scalyr" )
        ScalyrMonitor.run( self )
        
    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop the DockerLoggers
        for logger in self.docker_loggers:
            logger.stop( wait_on_join, join_timeout )
            self._logger.info( "Stopping %s - %s" % (logger.name, logger.stream) )



