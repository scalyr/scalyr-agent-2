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

import errno
import logging
import logging.handlers
import os
import os.path
import re
from socket import error as socket_error
import socket
import struct
import SocketServer
import threading
import time
import traceback
from string import Template
from threading import Timer

from scalyr_agent import ScalyrMonitor, define_config_option, AutoFlushingRotatingFileHandler
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_0, DEBUG_LEVEL_1, DEBUG_LEVEL_2
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_3, DEBUG_LEVEL_4, DEBUG_LEVEL_5
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.server_processors import RequestStream
from scalyr_agent.util import StoppableThread
from scalyr_agent.json_lib import JsonObject

import scalyr_agent.scalyr_logging as scalyr_logging
global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.syslog_monitor``',
                     convert_to=str, required_option=True)
define_config_option( __monitor__, 'protocols',
                     'Optional (defaults to ``tcp:601``). Lists the protocols and ports on which the agent will accept '
                     'messages. You can include one or more entries, separated by commas. Each entry must be of the '
                     'form ``tcp:NNN`` or ``udp:NNN``. Port numbers are optional, defaulting to 601 for TCP and 514 '
                     'for UDP',
                     convert_to=str, default='tcp')

define_config_option(__monitor__, 'accept_remote_connections',
                     'Optional (defaults to false). If true, the plugin will accept network connections from any host; '
                     'otherwise, it will only accept connections from localhost.',
                     default=False, convert_to=bool)

define_config_option( __monitor__, 'message_log',
                     'Optional (defaults to ``agent_syslog.log``). Specifies the file name under which syslog messages '
                     'are stored. The file will be placed in the default Scalyr log directory, unless it is an '
                     'absolute path',
                     convert_to=str, default='agent_syslog.log')

define_config_option( __monitor__, 'parser',
                     'Optional (defaults to ``agentSyslog``). Defines the parser name associated with the log file',
                     convert_to=str, default='agentSyslog')

define_config_option( __monitor__, 'tcp_buffer_size',
                     'Optional (defaults to 8K).  The maximum buffer size for a single TCP syslog message.  '
                     'Note: RFC 5425 (syslog over TCP/TLS) says syslog receivers MUST be able to support messages at least 2048 bytes long, and recommends they SHOULD '
                     'support messages up to 8192 bytes long.',
                     default=8192, min_value=2048, max_value=65536*1024, convert_to=int)

define_config_option( __monitor__, 'max_log_size',
                     'Optional (defaults to 50 MB). How large the log file will grow before it is rotated. Set to zero '
                     'for infinite size. Note that rotation is not visible in Scalyr; it is only relevant for managing '
                     'disk space on the host running the agent. However, a very small limit could cause logs to be '
                     'dropped if there is a temporary network outage and the log overflows before it can be sent to '
                     'Scalyr',
                     convert_to=int, default=50*1024*1024)

define_config_option( __monitor__, 'max_log_rotations',
                     'Optional (defaults to 2). The maximum number of log rotations before older log files are '
                     'deleted. Set to zero for infinite rotations.',
                     convert_to=int, default=2)

define_config_option( __monitor__, 'log_flush_delay',
                     'Optional (defaults to 1.0). The time to wait in seconds between flushing the log file containing '
                     'the syslog messages.',
                     convert_to=float, default=1.0)

define_config_option(__monitor__, 'mode',
                     'Optional (defaults to "syslog"). If set to "docker", the plugin will enable extra functionality '
                     'to properly receive log lines sent via the `docker_monitor`.  In particular, the plugin will '
                     'check for container ids in the tags of the incoming lines and create log files based on their '
                     'container names.',
                     default='syslog', convert_to=str)

define_config_option( __monitor__, 'docker_regex',
                     'Regular expression for parsing out docker logs from a syslog message when the tag sent to syslog '
                     'only has the container id.  If a message matches this regex then everything *after* '
                     'the full matching expression will be logged to a file called docker-<container-name>.log',
                     convert_to=str, default='^.*docker/([a-z0-9]{12})\[\d+\]: ')

define_config_option( __monitor__, 'docker_regex_full',
                     'Regular expression for parsing out docker logs from a syslog message when the tag sent to syslog '
                     'included both the container name and id.  If a message matches this regex then everything *after* '
                     'the full matching expression will be logged to a file called docker-<container-name>.log',
                     convert_to=str, default='^.*docker/([^/]+)/([^[]+)\[\d+\]: ')

define_config_option( __monitor__, 'docker_expire_log',
                     'Optional (defaults to 300).  The number of seconds of inactivity from a specific container before '
                     'the log file is removed.  The log will be created again if a new message comes in from the container',
                     default=300, convert_to=int)

define_config_option( __monitor__, 'docker_accept_ips',
                     'Optional.  A list of ip addresses to accept connections from if being run in a docker container. '
                     'Defaults to a list with the ip address of the default docker bridge gateway. '
                     'If accept_remote_connections is true, this option does nothing.')

define_config_option(__monitor__, 'docker_api_socket',
                     'Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket used to communicate with '
                     'the docker API. This is only used when `mode` is set to `docker` to look up container '
                     'names by their ids.  WARNING, you must also set the `api_socket` configuration option in the '
                     'docker monitor to this same value.\n'
                     'Note:  You need to map the host\'s /run/docker.sock to the same value as specified here, using '
                     'the -v parameter, e.g.\n'
                     '\tdocker run -v /run/docker.sock:/var/scalyr/docker.sock ...',
                     convert_to=str, default='/var/scalyr/docker.sock')

define_config_option(__monitor__, 'docker_api_version',
                     'Optional (defaults to \'auto\'). The version of the Docker API to use when communicating to '
                     'docker.  WARNING, you must also set the `docker_api_version` configuration option in the docker '
                     'monitor to this same value.', convert_to=str, default='auto')

define_config_option(__monitor__, 'docker_logfile_template',
                     'Optional (defaults to \'containers/${CNAME}.log\'). The template used to create the log '
                     'file paths for save docker logs sent by other containers via syslog.  The variables $CNAME and '
                     '$CID will be substituted with the name and id of the container that is emitting the logs.  If '
                     'the path is not absolute, then it is assumed to be relative to the main Scalyr Agent log '
                     'directory.', convert_to=str, default='containers/${CNAME}.log')

define_config_option(__monitor__, 'docker_cid_cache_lifetime_secs',
                     'Optional (defaults to 300). Controls the docker id to container name cache expiration.  After '
                     'this number of seconds of inactivity, the cache entry will be evicted.',
                     convert_to=float, default=300.0)

define_config_option(__monitor__, 'docker_cid_clean_time_secs',
                     'Optional (defaults to 5.0). The number seconds to wait between cleaning the docker id to '
                     'container name cache.',
                     convert_to=float, default=5.0)

def _get_default_gateway():
    """Read the default gateway directly from /proc."""
    result = None
    fh = None
    try:
        fh = open("/proc/net/route")
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue

            result = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    finally:
        if fh:
            fh.close()

    return result

class SyslogFrameParser(object):
    """Simple abstraction that implements a 'parse_request' that can be used to parse incoming syslog
    messages.  These will either be terminated by a newline (or crlf) sequence, or begin with an
    integer specifying the number of octects in the message.  The parser performs detection of
    which type the message is and handles it appropriately.
    """
    def __init__(self, max_request_size):
        """Creates a new instance.

        @param max_request_size: The maximum number of bytes that can be contained in an individual request.
        """
        self.__max_request_size = max_request_size

    def parse_request(self, input_buffer, _):
        """Returns the next complete request from 'input_buffer'.

        If the message is framed, then if the number of bytes in the buffer is >= the number of bytes in
        the frame, then return the entire frame, otherwise return None and no bytes are consumed.

        If the message is unframed, then if there is a complete line at the start of 'input_buffer' (where complete line is determined by it
        ending in a newline character), then consumes those bytes from 'input_buffer' and returns the string
        including the newline.  Otherwise None is returned and no bytes are consumed from 'input_buffer'

        @param input_buffer: The bytes to read.
        @param _: The number of bytes available in 'input_buffer'. (not used)

        @return: A string containing the next complete request read from 'input_buffer' or None if there is none.

            RequestSizeExceeded if a line is found to exceed the maximum request size.
            ValueError if the message starts with a digit (e.g. is framed) but the frame size is not delimited by a space
        """
        new_position = None
        try:
            new_position = input_buffer.tell()
            buf = input_buffer.read(self.__max_request_size + 1)

            bytes_received = len(buf)

            if bytes_received > self.__max_request_size:
                # We just consume these bytes if the line did exceeded the maximum.  To some degree, this
                # typically does not matter since once we see any error on a connection, we close it down.
                global_log.warning( "SyslogFrameParser - bytes received exceed buffer size.  Some logs may be lost." )
                new_position = None
                raise RequestSizeExceeded(bytes_received, self.__max_request_size)

            framed = False
            if bytes_received > 0:
                c = buf[0]
                framed = (c >= '0' and c <= '9')
            else:
                return None

            #offsets contains the start and end offsets of the message within the buffer.
            #an end offset of 0 indicates there is not a valid message in the buffer yet
            offsets = (0, 0)
            if framed:
                offsets = self._framed_offsets( buf, bytes_received )
            else:
                offsets = self._unframed_offsets( buf, bytes_received )

            if offsets[1] != 0:
                #our new position is going to be the previous position plus the end offset
                new_position += offsets[1]

                #return a slice containing the full message
                return buf[ offsets[0]:offsets[1] ]

            return None
        finally:
            if new_position is not None:
                input_buffer.seek(new_position)

    def _framed_offsets( self, frame_buffer, length ):
        result = (0, 0)
        pos = frame_buffer.find( ' ' )
        if pos != -1:
            frame_size = int( frame_buffer[0:pos] )
            message_offset = pos + 1
            if length - message_offset >= frame_size:
                result = (message_offset, message_offset + frame_size)

        return result

    def _unframed_offsets( self, frame_buffer, length ):
        result = (0, 0)
        pos = frame_buffer.find( '\n' )
        if pos != -1:
            result = (0, pos + 1)

        return result

class SyslogUDPHandler( SocketServer.BaseRequestHandler ):
    """Class that reads data from a UDP request and passes it to
    a protocol neutral handler
    """
    def handle( self ):
        self.server.syslog_handler.handle( self.request[0].strip() )

class SyslogTCPHandler( SocketServer.BaseRequestHandler ):
    """Class that reads data from a TCP request and passes it to
    a protocol neutral handler
    """
    def handle( self ):
        try:
            buffer_size = self.server.tcp_buffer_size
            parser = SyslogFrameParser( buffer_size )
            request_stream = RequestStream(self.request, parser.parse_request,
                                           max_buffer_size=buffer_size,
                                           max_request_size=buffer_size,
                                           blocking=False)

            global_log.log(scalyr_logging.DEBUG_LEVEL_1, "SyslogTCPHandler.handle - created request_stream. Thread: %d", threading.current_thread().ident )
            while self.server.is_running() and not request_stream.is_closed():
                data = request_stream.read_request()
                if data is not None:
                    self.server.syslog_handler.handle( data.strip() )
                else:
                    # don't hog the CPU
                    time.sleep( 0.01 )

        except Exception, e:
            global_log.warning( "Error handling request: %s\n\t%s", str( e ), traceback.format_exc() )

        global_log.log(scalyr_logging.DEBUG_LEVEL_1, "SyslogTCPHandler.handle - closing request_stream. Thread: %d", threading.current_thread().ident )


class SyslogUDPServer( SocketServer.ThreadingMixIn, SocketServer.UDPServer ):
    """Class that creates a UDP SocketServer on a specified port
    """
    def __init__( self, port, bind_address, verifier ):

        self.__verifier = verifier
        address = ( bind_address, port )
        global_log.log(scalyr_logging.DEBUG_LEVEL_1, "UDP Server: binding socket to %s" % str( address ) )

        self.allow_reuse_address = True
        SocketServer.UDPServer.__init__( self, address, SyslogUDPHandler )

    def verify_request( self, request, client_address ):
        return self.__verifier.verify_request( client_address )

    def set_run_state( self, run_state ):
        """Do Nothing only TCP connections need the runstate"""
        pass

class SyslogTCPServer( SocketServer.ThreadingMixIn, SocketServer.TCPServer ):
    """Class that creates a TCP SocketServer on a specified port
    """
    def __init__( self, port, tcp_buffer_size, bind_address, verifier ):

        self.__verifier = verifier
        address = ( bind_address, port )
        global_log.log(scalyr_logging.DEBUG_LEVEL_1, "TCP Server: binding socket to %s" % str( address ) )

        self.allow_reuse_address = True
        self.__run_state = None
        self.tcp_buffer_size = tcp_buffer_size
        SocketServer.TCPServer.__init__( self, address, SyslogTCPHandler )

    def verify_request( self, request, client_address ):
        return self.__verifier.verify_request( client_address )

    def set_run_state( self, run_state ):
        self.__run_state = run_state

    def is_running( self ):
        if self.__run_state:
            return self.__run_state.is_running()

        return False

class SyslogHandler(object):
    """Protocol neutral class for handling messages that come in from a syslog server

    @param line_reporter A function to invoke whenever the server handles lines.  The number of lines
        must be supplied as the first argument.
    """
    def __init__( self, logger, line_reporter, config, server_host, log_path, get_log_watcher ):

        docker_logging = config.get('mode') == 'docker'
        self.__docker_regex = None
        self.__docker_regex_full = None
        self.__docker_id_resolver = None
        self.__docker_file_template = None

        if docker_logging:
            self.__docker_regex_full = self.__get_regex(config, 'docker_regex_full')
            self.__docker_regex = self.__get_regex(config, 'docker_regex')
            self.__docker_file_template = Template(config.get('docker_logfile_template'))
            from scalyr_agent.builtin_monitors.docker_monitor import ContainerIdResolver
            self.__docker_is_resolver = ContainerIdResolver(config.get('docker_api_socket'),
                                                            config.get('docker_api_version'),
                                                            global_log,
                                                            cache_expiration_secs=config.get(
                                                                'docker_cid_cache_lifetime_secs'),
                                                            cache_clean_secs=config.get('docker_cid_clean_time_secs'))

        self.__log_path = log_path
        self.__server_host = server_host

        self.__get_log_watcher = get_log_watcher

        self.__logger = logger
        self.__line_reporter = line_reporter
        self.__docker_logging = docker_logging
        self.__docker_loggers = {}
        self.__logger_lock = threading.Lock()

        self.__docker_expire_log = config.get( 'docker_expire_log' )

        self.__max_log_rotations = config.get( 'max_log_rotations' )
        self.__max_log_size = config.get( 'max_log_size' )
        self.__flush_delay = config.get('log_flush_delay')

    def __get_regex(self, config, field_name):
        value = config.get(field_name)
        if len(value) > 0:
            return re.compile(value)
        else:
            return None

    def __create_log_config( self, cname, cid ):

        full_path = os.path.join( self.__log_path, self.__docker_file_template.safe_substitute(
            {'CID': cid, 'CNAME': cname}))
        log_config = {
            'parser': 'agentSyslogDocker',
            'path': full_path
        }

        return log_config

    def __extra_attributes( self, cname, cid ):

        attributes = None
        try:
            attributes = JsonObject( {
                "monitor": "agentSyslog",
                "containerName": cname,
                "containerId": cid
            } )

            if self.__server_host:
                attributes['serverHost'] = self.__server_host


        except Exception, e:
            self.__logger.error( "Error setting docker logger attribute in SyslogMonitor" )
            raise

        return attributes

    def __create_log_file( self, cname, cid, log_config ):
        """create our own rotating logger which will log raw messages out to disk.
        """
        result = None
        try:
            result = AutoFlushingRotatingFileHandler( filename = log_config['path'],
                                                                  maxBytes = self.__max_log_size,
                                                                  backupCount = self.__max_log_rotations,
                                                                  flushDelay = self.__flush_delay)

        except Exception, e:
            self.__logger.error( "Unable to open SyslogMonitor log file: %s" % str( e ) )
            result = None

        return result

    def __extract_container_name_and_id(self, data):
        """Attempts to extract the container id and container name from the log line received from Docker via
        syslog.

        First, attempts to extract container id using `__docker_regex` and look up the container name via Docker.
        If that fails, attempts to extract the container id and container name using the `__docker_regex_full`.

        @param data: The incoming line
        @type data: str
        @return: The container name, container id, and the rest of the line if extract was successful.  Otherwise,
            None, None, None.
        @rtype: str, str, str
        """
        if self.__docker_regex is not None:
            m = self.__docker_regex.match(data)
            if m is not None:
                self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Matched cid-only syslog format')
                cid = m.group(1)
                cname = self.__docker_is_resolver.lookup(cid)

                if cid is not None and cname is not None:
                    self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Resolved container name')
                    return cname, cid, data[m.end():]

        if self.__docker_regex_full is not None:
            m = self.__docker_regex_full.match(data)
            if m is not None and m.lastindex == 2:
                self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Matched cid/cname syslog format')
                return m.group(1), m.group(2), data[m.end():]

        self.__logger.log(scalyr_logging.DEBUG_LEVEL_3, 'Could not extract cid/cname for "%s"', data)

        return None, None, None

    def __handle_docker_logs( self, data ):

        watcher = None
        module = None
        # log watcher for adding/removing logs from the agent
        if self.__get_log_watcher:
            watcher, module = self.__get_log_watcher()

        (cname, cid, line_content) = self.__extract_container_name_and_id(data)

        if cname is not None and cid is not None:
            logger = None
            try:
                self.__logger_lock.acquire()

                # check if we already have a logger for this container
                # and if not, then create it
                if cname not in self.__docker_loggers:
                    info = dict()

                    # get the config and set the attributes
                    info['log_config'] = self.__create_log_config( cname, cid )
                    info['cid'] = cid
                    attributes = self.__extra_attributes( cname, cid )
                    if attributes:
                        info['log_config']['attributes'] = attributes

                    # create the physical log files
                    info['logger'] = self.__create_log_file( cname, cid, info['log_config'] )
                    info['last_seen'] = time.time()

                    # if we created the log file
                    if info['logger']:
                        # add it to the main scalyr log watcher
                        if watcher and module:
                            info['log_config'] = watcher.add_log_config( module, info['log_config'] )

                        # and keep a record for ourselves
                        self.__docker_loggers[cname] = info
                    else:
                        self.__logger.warn( "Unable to create logger for %s." % cname )
                        return

                # at this point __docker_loggers will always contain
                # a logger for this container name, so log the message
                # and mark the time
                logger = self.__docker_loggers[cname]
            finally:
                self.__logger_lock.release()

            if logger:
                logger['logger'].write(line_content)
                logger['last_seen'] = time.time()

        # find out which if any of the loggers in __docker_loggers have
        # expired
        expired = []
        currentTime = time.time()

        try:
            self.__logger_lock.acquire()
            for key, info in self.__docker_loggers.iteritems():
                if currentTime - info['last_seen'] > self.__docker_expire_log:
                    expired.append( key )

            # remove all the expired loggers
            for key in expired:
                info = self.__docker_loggers.pop( key, None )
                if info:
                    info['logger'].close()
                    if watcher and module:
                        watcher.remove_log_path( module, info['log_config']['path'] )
        finally:
            self.__logger_lock.release()

    def handle( self, data ):
        if self.__docker_logging:
            self.__handle_docker_logs( data )
        else:
            self.__logger.info( data )
        # We add plus one because the calling code strips off the trailing new lines.
        self.__line_reporter(data.count('\n') + 1)

class RequestVerifier( object ):
    """Determines whether or not a request should be processed
       based on the state of various config options
    """

    def __init__( self, accept_remote, accept_ips, docker_logging ):
        self.__accept_remote = accept_remote
        self.__accept_ips = accept_ips
        self.__docker_logging = docker_logging

    def verify_request( self, client_address ):
        result = True
        address, port = client_address
        if self.__docker_logging:
            result = self.__accept_remote or address in self.__accept_ips

        if not result:
            global_log.log(scalyr_logging.DEBUG_LEVEL_4, "Rejecting request from %s" % str( client_address ) )

        return result


class SyslogServer(object):
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures a handler to process messages.

    This removes the need for users of this class to care about the underlying protocol being used

    @param line_reporter A function to invoke whenever the server handles lines.  The number of lines
        must be supplied as the first argument.
    """
    def __init__( self, protocol, port, logger, config, line_reporter, accept_remote=False, server_host=None, log_path=None, get_log_watcher=None):
        server = None

        accept_ips = config.get( 'docker_accept_ips' );
        if accept_ips == None:
            accept_ips = []
            gateway_ip = _get_default_gateway()
            if gateway_ip:
                accept_ips = [ gateway_ip ]

        logger.log(scalyr_logging.DEBUG_LEVEL_2, "Accept ips are: %s" % str( accept_ips ) );

        docker_logging = config.get( 'mode' ) == 'docker'

        verifier = RequestVerifier( accept_remote, accept_ips, docker_logging )

        try:
            bind_address = self.__get_bind_address( docker_logging=docker_logging, accept_remote=accept_remote )
            if protocol == 'tcp':
                global_log.log(scalyr_logging.DEBUG_LEVEL_2, "Starting TCP Server" )
                server = SyslogTCPServer( port, config.get( 'tcp_buffer_size' ), bind_address=bind_address, verifier=verifier )
            elif protocol == 'udp':
                global_log.log(scalyr_logging.DEBUG_LEVEL_2, "Starting UDP Server" )
                server = SyslogUDPServer( port, bind_address=bind_address, verifier=verifier )

        except socket_error, e:
            if e.errno == errno.EACCES and port < 1024:
                raise Exception( 'Access denied when trying to create a %s server on a low port (%d). '
                                 'Please try again on a higher port, or as root.' % (protocol, port)  )
            else:
                raise

        #don't continue if the config had a protocol we don't recognize
        if server is None:
            raise Exception( 'Unknown value \'%s\' specified for SyslogServer \'protocol\'.' % protocol )

        #create the syslog handler, and add to the list of servers
        server.syslog_handler = SyslogHandler( logger, line_reporter, config, server_host, log_path, get_log_watcher )
        server.syslog_transport_protocol = protocol
        server.syslog_port = port

        self.__server = server
        self.__thread = None

    def __get_bind_address( self, docker_logging=False, accept_remote=False ):
        result = 'localhost'
        if accept_remote:
            result = ''
        else:
            # check if we are running inside a docker container
            if docker_logging and os.path.isfile( '/.dockerenv' ):
                # need to accept from remote ips
                result = ''
        return result


    def __prepare_run_state( self, run_state ):
        if run_state is not None:
            server = self.__server
            server.set_run_state( run_state )
            #shutdown is only available from python 2.6 onwards
            #need to think of what to do for 2.4, which will hang on shutdown when run as standalone
            if hasattr( server, 'shutdown' ):
                run_state.register_on_stop_callback( server.shutdown )

    def start( self, run_state ):
        self.__prepare_run_state( run_state )
        self.__server.serve_forever()

    def start_threaded( self, run_state ):
        self.__prepare_run_state( run_state )
        self.__thread = StoppableThread( target=self.start, name="Syslog monitor thread for %s:%d" % (self.__server.syslog_transport_protocol, self.__server.syslog_port) )
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        if self.__thread is not None:
            self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )


class SyslogMonitor( ScalyrMonitor ):
    """
# Syslog Monitor

The Syslog monitor allows the Scalyr Agent to act as a syslog server, proxying logs from any application or device
that supports syslog. It can recieve log messages via the syslog TCP or syslog UDP protocols.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

This sample will configure the agent to accept syslog messages on TCP port 601 and UDP port 514, from localhost
only:

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.syslog_monitor",
        protocols:                 "tcp:601, udp:514",
        accept_remote_connections: false
      }
    ]

You can specify any number of protocol/port combinations. Note that on Linux, to use port numbers 1024 or lower,
the agent must be running as root.

You may wish to accept syslog connections from other devices on the network, such as a firewall or router which
exports logs via syslog. Set ``accept_remote_connections`` to true to allow this.

Additional options are documented in the Configuration Reference section, below.


## Log files and parsers

By default, all syslog messages are written to a single log file, named ``agentSyslog.log``. You can use the
``message_log`` option to specify a different file name (see Configuration Reference).

If you'd like to send messages from different devices to different log files, you can include multiple syslog_monitor
stanzas in your configuration file. Specify a different ``message_log`` for each monitor, and have each listen on a
different port number. Then configure each device to send to the appropriate port.

syslog_monitor logs use a parser named ``agentSyslog``. To set up parsing for your syslog messages, go to the
[Parser Setup Page](/parsers?parser=agentSyslog) and click {{menuRef:Leave it to Us}} or
{{menuRef:Build Parser By Hand}}. If you are using multiple syslog_monitor stanzas, you can specify a different
parser for each one, using the ``parser`` option.


## Sending messages via syslog

To send messages to the Scalyr Agent using the syslog protocol, you must configure your application or network
device. The documentation for your application or device should include instructions. We'll be happy to help out;
please drop us a line at [support@scalyr.com](mailto:support@scalyr.com).


### Rsyslogd

To send messages from another Linux host, you may wish to use the popular ``rsyslogd`` utility. rsyslogd has a
powerful configuration language, and can be used to forward all logs or only a selected set of logs.

Here is a simple example. Suppose you have configured Scalyr's Syslog Monitor to listen on TCP port 601, and you
wish to use rsyslogd on the local host to upload system log messages of type ``authpriv``. You would add the following
lines to your rsyslogd configuration, which is typically in ``/etc/rsyslogd.conf``:

    # Send all authpriv messasges to Scalyr.
    authpriv.*                                              @@localhost:601

Make sure that this line comes before any other filters that could match the authpriv messages. The ``@@`` prefix
specifies TCP.


## Viewing Data

Messages uploaded by the Syslog Monitor will appear as an independent log file on the host where the agent is
running. You can find this log file in the [Overview](/logStart) page. By default, the file is named "agentSyslog.log".
    """
    def _initialize( self ):
        #the main server
        self.__server = None

        #any extra servers if we are listening for multiple protocols
        self.__extra_servers = []

        #build list of protocols and ports from the protocol option
        self.__server_list = self.__build_server_list( self._config.get( 'protocols' ) )

        #our disk logger and handler
        self.__disk_logger = None
        self.__log_handler = None

        #whether or not to accept only connections created on this localhost.
        self.__accept_remote_connections = self._config.get( 'accept_remote_connections' )

        self.__server_host = None
        self.__log_path = ''
        if self._global_config:
            self.__log_path = self._global_config.agent_log_path

            if self._global_config.server_attributes:
                if 'serverHost' in self._global_config.server_attributes:
                    self.__server_host = self._global_config.server_attributes['serverHost']

        self.__log_watcher = None
        self.__module = None

        #configure the logger and path
        message_log = self._config.get( 'message_log' )

        self.log_config = {
            'parser': self._config.get( 'parser' ),
            'path': message_log,
        }

        self.__flush_delay = self._config.get('log_flush_delay')
        try:
            attributes = JsonObject( { "monitor": "agentSyslog" } )
            self.log_config['attributes'] = attributes
        except Exception, e:
            self._logger.error( "Error setting monitor attribute in SyslogMonitor" )

        self.__max_log_size = self._config.get( 'max_log_size' )
        self.__max_log_rotations = self._config.get( 'max_log_rotations' )


    def __build_server_list( self, protocol_string ):
        """Builds a list containing (protocol, port) tuples, based on a comma separated list
        of protocols and optional ports e.g. protocol[:port], protocol[:port]
        """

        #split out each protocol[:port]
        protocol_list = [p.strip().lower() for p in protocol_string.split(',')]

        if len( protocol_list ) == 0:
            raise Exception('Invalid config state for Syslog Monitor. '
                            'No protocols specified')

        default_ports = { 'tcp': 601,
                          'udp': 514,
                        }

        server_list = []

        #regular expression matching protocol:port
        port_re = re.compile( '^(tcp|udp):(\d+)$' )
        for p in protocol_list:

            #protocol defaults to the full p for when match fails
            protocol = p
            port = 0

            m = port_re.match( p )
            if m:
                protocol = m.group(1)
                port = int( m.group(2) )

            if protocol in default_ports:
                #get the default port for this protocol if none was specified
                if port == 0:
                    port = default_ports[protocol]
            else:
                raise Exception( 'Unknown value \'%s\' specified for SyslogServer \'protocol\'.' % protocol )

            #only allow ports between 1 and 65535
            if port < 1 or port > 65535:
                raise Exception( 'Port values must be in the range 1-65535.  Current value: %d.' % port )

            server_list.append( (protocol, port) )

        #return a list with duplicates removed
        return list( set( server_list ) )


    def open_metric_log( self ):
        """Override open_metric_log to prevent a metric log from being created for the Syslog Monitor
        and instead create our own logger which will log raw messages out to disk.
        """
        name = __name__ + '.syslog'
        self.__disk_logger = logging.getLogger( name )

        #assume successful for when the logger handler has already been created
        success = True

        #only configure once -- assumes all configuration happens on the same thread
        if len( self.__disk_logger.handlers ) == 0:
            #logger handler hasn't been created yet, so assume unsuccssful
            success = False
            try:
                self.__log_handler = AutoFlushingRotatingFileHandler( filename = self.log_config['path'],
                                                                      maxBytes = self.__max_log_size,
                                                                      backupCount = self.__max_log_rotations,
                                                                      flushDelay = self.__flush_delay)

                formatter = logging.Formatter()
                self.__log_handler.setFormatter( formatter )
                self.__disk_logger.addHandler( self.__log_handler )
                self.__disk_logger.setLevel( logging.INFO )
                self.__disk_logger.propagate = False
                success = True
            except Exception, e:
                self._logger.error( "Unable to open SyslogMonitor log file: %s" % str( e ) )

        return success

    def close_metric_log( self ):
        if self.__log_handler:
            self.__disk_logger.removeHandler( self.__log_handler )
            self.__log_handler.close()

    def set_log_watcher( self, log_watcher ):
        self.__log_watcher = log_watcher

    def __get_log_watcher( self ):
        return (self.__log_watcher, self)

    def run( self ):
        def line_reporter(num_lines):
            self.increment_counter(reported_lines=num_lines)

        try:
            if self.__disk_logger is None:
                raise Exception( "No disk logger available for Syslog Monitor" )

            #create the main server from the first item in the server list
            protocol = self.__server_list[0]
            self.__server = SyslogServer( protocol[0], protocol[1], self.__disk_logger, self._config,
                                          line_reporter, accept_remote=self.__accept_remote_connections,
                                          server_host=self.__server_host, log_path=self.__log_path,
                                          get_log_watcher=self.__get_log_watcher )

            #iterate over the remaining items creating servers for each protocol
            for p in self.__server_list[1:]:
                server = SyslogServer( p[0], p[1], self.__disk_logger, self._config,
                                       line_reporter, accept_remote=self.__accept_remote_connections,
                                       server_host=self.__server_host, log_path=self.__log_path,
                                       get_log_watcher=self.__get_log_watcher )
                self.__extra_servers.append( server )

            #start any extra servers in their own threads
            for server in self.__extra_servers:
                server.start_threaded( self._run_state )

            #start the main server
            self.__server.start( self._run_state )

        except Exception, e:
            self._logger.exception('Monitor died due to exception:', error_code='failedMonitor')
            raise

    def stop(self, wait_on_join=True, join_timeout=5):

        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop any extra servers
        for server in self.__extra_servers:
            server.stop( wait_on_join, join_timeout )

