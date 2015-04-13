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

from scalyr_agent import ScalyrMonitor, define_config_option
from scalyr_agent.util import StoppableThread

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.syslog_monitor``',
                     convert_to=str, required_option=True)
define_config_option( __monitor__, 'protocol',
                     'Optional (defaults to udp). Defines which transport protocols and ports to listen for syslog messages on. '
                     'Valid values can be \'udp\' or \'tcp\', which can be bare, e.g. \'udp\' or combined with a port number, e.g. \'udp:10514\'.  '
                     'Multiple values can be combined with a comma to specify both, e.g. \'udp, tcp',
                     convert_to=str, default='udp')

define_config_option( __monitor__, 'default_udp_port',
                     'Optional (defaults to 514). Defines which port to listen for udp syslog messages on if no port specified in the protocol option. '
                     'Note: ports lower than 1024 require the agent to run with root privileges. '
                     'Not used if ``protocol`` does not specify udp',
                     default=514, min_value=1, max_value=65535, convert_to=int)

define_config_option( __monitor__, 'default_tcp_port',
                     'Optional (defaults to 6514). Default port to listen for tcp syslog messages on if no port specified in the protocol option. '
                     'Not used if ``protocol`` does not specify tcp',
                     default=6514, min_value=1, max_value=65535, convert_to=int)

define_config_option( __monitor__, 'message_log',
                     'Optional (defaults to syslog_messages.log). Defines a log file name for storing syslog messages that come in over the network. '
                     'Note: the file will be placed in the default Scalyr log directory unless it is an absolute path.',
                     convert_to=str, default='syslog_messages.log')

define_config_option( __monitor__, 'max_log_size',
                     'Optional (defaults to 100 MB - 100*1024*1024). The maximum file size of the syslog messages log before log rotation occurs. '
                     'Set to zero for infinite size.',
                     convert_to=int, default=100*1024*1024)

define_config_option( __monitor__, 'max_log_rotations',
                     'Optional (defaults to 5). The maximum number of log rotations before deleting old logs. '
                     'Set to zero for infinite rotations.',
                     convert_to=int, default=5)


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
        data = self.request.recv( 1024 ).strip()
        self.server.syslog_handler.handle( data )

class SyslogUDPServer( SocketServer.ThreadingMixIn, SocketServer.UDPServer ):
    """Class that creates a UDP SocketServer on a specified port
    """
    def __init__( self, port ):
        address = ( 'localhost', port )
        self.allow_reuse_address = True
        SocketServer.UDPServer.__init__( self, address, SyslogUDPHandler )

class SyslogTCPServer( SocketServer.ThreadingMixIn, SocketServer.TCPServer ):
    """Class that creates a TCP SocketServer on a specified port
    """
    def __init__( self, port ):
        address = ( 'localhost', port )
        self.allow_reuse_address = True
        SocketServer.TCPServer.__init__( self, address, SyslogTCPHandler )

class SyslogHandler:
    """Protocol neutral class for handling messages that come in from a syslog server
    """
    def __init__( self, logger ):
        self.__logger = logger

    def handle( self, data ):
        #TODO: Make this work better
        self.__logger.info( data )

class SyslogServer:
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures a handler to process messages.

    This removes the need for users of this class to care about the underlying protocol being used
    """
    def __init__( self, protocol, port, logger ):
        server = None
        try:
            if protocol == 'tcp':
                server = SyslogTCPServer( port )
            elif protocol == 'udp':
                server = SyslogUDPServer( port )

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

    def start( self, run_state ):
        if run_state != None:
            server = self.__server
            #shutdown is only available from python 2.6 onwards
            #need to think of what to do for 2.4, which will hang on shutdown when run as standalone
            if hasattr( server, 'shutdown' ):
                run_state.register_on_stop_callback( server.shutdown )

        self.__server.serve_forever()

    def start_threaded( self, run_state ):
        self.__thread = StoppableThread( target=self.start, name="Syslog monitor thread for %s:%d" % (self.__server.syslog_transport_protocol, self.__server.syslog_port) )
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        if self.__thread != None:
            self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )


class SyslogMonitor( ScalyrMonitor ):
    """Monitor plugin for syslog messages

    This plugin listens on one or more ports/protocols for syslog messages, and uploads them
    to Scalyr.
    """
    def _initialize( self ):
        #the main server
        self.__server = None

        #any extra servers if we are listening for multiple protocols
        self.__extra_servers = []

        #build list of protocols and ports from the protocol option
        self.__server_list = self.__build_server_list( self._config.get( 'protocol' ) )

        #configure the logger and path
        message_log = self._config.get( 'message_log' )

        self.log_config = {
            'parser': 'systemLog',
            'path': message_log
        }

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

        default_ports = { 'tcp': self._config.get( 'default_tcp_port' ),
                          'udp': self._config.get( 'default_udp_port' )
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

    def __get_disk_logger( self, log_name, max_bytes, backup_count ):
        name = __name__ + '.syslog'
        log = logging.Logger( name )

        #only configure once -- assumes all configuration happens on the same thread
        import sys
        if len( log.handlers ) == 0:
            print >>sys.stdout, "No handlers yet for ", name
            handler = logging.handlers.RotatingFileHandler( filename = log_name, maxBytes = max_bytes, backupCount = backup_count )
            formatter = logging.Formatter()
            handler.setFormatter( formatter )
            log.addHandler( handler )
            log.setLevel( logging.INFO )
        else:
            print >>sys.stdout, "Already has handlers: ", name
        return log



    def run( self ):
        try:
            self.__disk_logger = self.__get_disk_logger( self.log_config['path'], self.__max_log_size, self.__max_log_rotations )

            #create the main server from the first item in the server list
            protocol = self.__server_list[0]
            self.__server = SyslogServer( protocol[0], protocol[1], self.__disk_logger )

            #iterate over the remaining items creating servers for each protocol
            for p in self.__server_list[1:]:
                server = SyslogServer( p[0], p[1], self.__disk_logger )
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

