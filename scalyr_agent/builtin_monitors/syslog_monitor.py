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
                     'Optional (defaults to tcp). Defines which transport protocols and ports to listen for syslog messages on. '
                     'Valid values can be \'udp\' or \'tcp\', which can be bare, e.g. \'udp\' or combined with a port number, e.g. \'udp:10514\'.  '
                     'Multiple values can be combined with a comma to specify both, e.g. \'udp, tcp\'.  If no port is '
                     'specified, then 514 is used for \'udp\' and 601 is used for \'tcp\'.',
                     convert_to=str, default='tcp')

define_config_option(__monitor__, 'accept_remote_connections',
                     'Optional (defaults to false). If true, the plugin will accept network connections from any host, '
                     'instead of just from localhost.',
                     default=False, convert_to=bool)

define_config_option( __monitor__, 'message_log',
                     'Optional (defaults to agent_syslog.log). Defines a log file name for storing syslog messages that are received by the agent syslog monitor. '
                     'Note: the file will be placed in the default Scalyr log directory unless it is an absolute path.',
                     convert_to=str, default='agent_syslog.log')

define_config_option( __monitor__, 'parser',
                     'Optional (defaults to agentSyslog). Defines the parser that should be specified for the message_log file.',
                     convert_to=str, default='agentSyslog')

define_config_option( __monitor__, 'tcp_buffer_size',
                     'Optional (defaults to 8K).  The maximum buffer size for a single TCP syslog message.  '
                     'Note: RFC 5425 (syslog over TCP/TLS) says syslog receivers MUST be able to support messages at least 2048 bytes long, and recommends they SHOULD '
                     'support messages up to 8192 bytes long.',
                     default=8192, min_value=2048, max_value=65536, convert_to=int)

define_config_option( __monitor__, 'max_log_size',
                     'Optional (defaults to 100 MB - 100*1024*1024). The maximum file size of the syslog messages log before log rotation occurs. '
                     'Set to zero for infinite size.',
                     convert_to=int, default=100*1024*1024)

define_config_option( __monitor__, 'max_log_rotations',
                     'Optional (defaults to 5). The maximum number of log rotations before deleting old logs. '
                     'Set to zero for infinite rotations.',
                     convert_to=int, default=5)


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
    """
    def __init__( self, logger ):
        self.__logger = logger

    def handle( self, data ):
        self.__logger.info( data )

class SyslogServer(object):
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures a handler to process messages.

    This removes the need for users of this class to care about the underlying protocol being used
    """
    def __init__( self, protocol, port, logger, config, accept_remote=False):
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
        server.syslog_handler = SyslogHandler( logger )
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

The Syslog monitor can receive log messages received via the syslog protocol over either syslog  UDP or TCP/IP and
upload them to Scalyr.  This is useful for acting as a proxy between server applications that export their logs via
syslog and Scalyr.

The monitor accepts connections from the localhost (by default) and writes all received syslog messages to a single
log file (defaulting to ``agentSyslog.log``) which is then copied to Scalyr.  This log file is configured
to be parsed using the ``agentSyslog`` parser.  You may wish to edit this parser to parse the line according to your
specific syslog message format.

## Configuring Scalyr Agent

In order to use this monitor, you will first need to enable it in your agent's ``agent.json`` configuration file and
specify the protocol and ports to receive messages on.  A typical configuration fragment is shown below:

  monitors: [
    {
      module:              "scalyr_agent.builtin_monitors.syslog_monitor",
      protocols:            "tcp:601,udp:514"
    }
  ]

As the fragment demonstrates, you may listen on one or more protocol/port combinations using a comma-deliminated
list.  Only ``tcp`` or ``udp`` are allowed for the protocol specification, and any valid, unused port number is
allowed for the port.  Note, if you use ports 1024 or less on Linux, you must be sure your agent is running as root.

You may wish to accept syslog connections from other hosts than just localhost.  For example, you may have a
network device that cannot run the agent itself, but does use syslog to export its log.  You can configure
the Syslog Monitor to accept non-localhost connections by setting the ``accept_remote_connections`` configuration option
to true.  Here is a sample fragment that demonstrates this:

  monitors: [
    {
      module:                      "scalyr_agent.builtin_monitors.syslog_monitor",
      protocols:                   "tcp:601,udp:514",
      accept_remote_connections:   true
    }
  ]

See the options section below for more information about all of the available configuration options.

## Configuring syslog sources

After your agent is configured to accept syslog connections, you must then configure your log sources to send
messages to it.  If your application can send log messages directly, you will need to find instructions
on how to configure the syslog destination.  If you need help doing this, please feel free to e-mail
``contact@scalyr.com`` for help.

### Rsyslogd

Rsyslogd is a popular syslog server used on Linux machines.  It uses a very rich configuration language that allows
you to do complex operations with the syslog messages it receives, such as splitting them up into separate
log files by their log type or sending them to another syslog server over TCP/IP or UDP.

You may wish to configure rsyslogd to send a subset of the syslog messages generated by that server to
Scalyr.  There are many ways you can do this, but we will show you a simple example.

Suppose you wish to send all log messages with type ``authpriv`` to a the Syslog Monitor running on localhost over
TCP/IP using port 601. You would add the following lines to your rsyslogd configuration, which is typically stored
in ``/etc/rsyslogd.conf``:

  # Send all authpriv messasges to Scalyr.
  authpriv.*                                              @@localhost:601

You must ensure that the line appears in the file before any other filters that could match the authpriv messages.
Note, the ``@@`` prefix indicates TCP/IP should be used.  A single ``@`` indicates UDP.
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
        try:
            if self.__disk_logger == None:
                raise Exception( "No disk logger available for Syslog Monitor" )

            #create the main server from the first item in the server list
            protocol = self.__server_list[0]
            self.__server = SyslogServer( protocol[0], protocol[1], self.__disk_logger, self._config,
                                          accept_remote=self.__accept_remote_connections )

            #iterate over the remaining items creating servers for each protocol
            for p in self.__server_list[1:]:
                server = SyslogServer( p[0], p[1], self.__disk_logger, self._config,
                                       accept_remote=self.__accept_remote_connections )
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

