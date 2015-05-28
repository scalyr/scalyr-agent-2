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
import re
from socket import error as socket_error
import SocketServer
import time

from scalyr_agent import ScalyrMonitor, define_config_option
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.server_processors import RequestStream
from scalyr_agent.util import StoppableThread
from scalyr_agent.json_lib import JsonObject

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
                     default=8192, min_value=2048, max_value=65536, convert_to=int)

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
        buffer_size = self.server.tcp_buffer_size
        parser = SyslogFrameParser( buffer_size )
        request_stream = RequestStream(self.request, parser.parse_request,
                                       max_buffer_size=buffer_size,
                                       max_request_size=buffer_size)
        while self.server.is_running() and not request_stream.is_closed():
            data = request_stream.read_request()
            if data != None:
                self.server.syslog_handler.handle( data.strip() )
            #don't hog the cpu
            time.sleep( 0.01 )

class SyslogUDPServer( SocketServer.ThreadingMixIn, SocketServer.UDPServer ):
    """Class that creates a UDP SocketServer on a specified port
    """
    def __init__( self, port, accept_remote=False ):
        if not accept_remote:
            address = ( 'localhost', port )
        else:
            address = ('', port )

        self.allow_reuse_address = True
        SocketServer.UDPServer.__init__( self, address, SyslogUDPHandler )

    def set_run_state( self, run_state ):
        """Do Nothing only TCP connections need the runstate"""
        pass

class SyslogTCPServer( SocketServer.ThreadingMixIn, SocketServer.TCPServer ):
    """Class that creates a TCP SocketServer on a specified port
    """
    def __init__( self, port, tcp_buffer_size, accept_remote=False ):
        if not accept_remote:
            address = ( 'localhost', port )
        else:
            address = ('', port )

        self.allow_reuse_address = True
        self.__run_state = None
        self.tcp_buffer_size = tcp_buffer_size
        SocketServer.TCPServer.__init__( self, address, SyslogTCPHandler )

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
    def __init__( self, logger, line_reporter ):
        self.__logger = logger
        self.__line_reporter = line_reporter

    def handle( self, data ):
        self.__logger.info( data )
        # We add plus one because the calling code strips off the trailing new lines.
        self.__line_reporter(data.count('\n') + 1)

class SyslogServer(object):
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures a handler to process messages.

    This removes the need for users of this class to care about the underlying protocol being used

    @param line_reporter A function to invoke whenever the server handles lines.  The number of lines
        must be supplied as the first argument.
    """
    def __init__( self, protocol, port, logger, config, line_reporter, accept_remote=False):
        server = None
        try:
            if protocol == 'tcp':
                server = SyslogTCPServer( port, config.get( 'tcp_buffer_size' ), accept_remote=accept_remote )
            elif protocol == 'udp':
                server = SyslogUDPServer( port, accept_remote=accept_remote )

        except socket_error, e:
            if e.errno == errno.EACCES and port < 1024:
                raise Exception( 'Access denied when trying to create a %s server on a low port (%d). '
                                 'Please try again on a higher port, or as root.' % (protocol, port)  )
            else:
                raise

        #don't continue if the config had a protocol we don't recognize
        if server == None:
            raise Exception( 'Unknown value \'%s\' specified for SyslogServer \'protocol\'.' % protocol )

        #create the syslog handler, and add to the list of servers
        server.syslog_handler = SyslogHandler( logger, line_reporter )
        server.syslog_transport_protocol = protocol
        server.syslog_port = port

        self.__server = server
        self.__thread = None


    def __prepare_run_state( self, run_state ):
        if run_state != None:
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
        if self.__thread != None:
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

        #configure the logger and path
        message_log = self._config.get( 'message_log' )

        self.log_config = {
            'parser': self._config.get( 'parser' ),
            'path': message_log,
        }

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
                self.__log_handler = logging.handlers.RotatingFileHandler( filename = self.log_config['path'], maxBytes = self.__max_log_size, backupCount = self.__max_log_rotations )
                formatter = logging.Formatter()
                self.__log_handler.setFormatter( formatter )
                self.__disk_logger.addHandler( self.__log_handler )
                self.__disk_logger.setLevel( logging.INFO )
                success = True
            except Exception, e:
                self._logger.error( "Unable to open SyslogMonitor log file: %s" % str( e ) )

        return success

    def close_metric_log( self ):
        if self.__log_handler:
            self.__disk_logger.removeHandler( self.__log_handler )
            self.__log_handler.close()

    def run( self ):
        def line_reporter(num_lines):
            self.increment_counter(reported_lines=num_lines)

        try:
            if self.__disk_logger == None:
                raise Exception( "No disk logger available for Syslog Monitor" )

            #create the main server from the first item in the server list
            protocol = self.__server_list[0]
            self.__server = SyslogServer( protocol[0], protocol[1], self.__disk_logger, self._config,
                                          line_reporter, accept_remote=self.__accept_remote_connections )

            #iterate over the remaining items creating servers for each protocol
            for p in self.__server_list[1:]:
                server = SyslogServer( p[0], p[1], self.__disk_logger, self._config,
                                       line_reporter, accept_remote=self.__accept_remote_connections )
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

