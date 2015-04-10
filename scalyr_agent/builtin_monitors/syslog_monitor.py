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
from socket import error as socket_error
import SocketServer

from scalyr_agent import ScalyrMonitor, define_config_option
from scalyr_agent.util import StoppableThread

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.syslog_monitor``',
                     convert_to=str, required_option=True)
define_config_option( __monitor__, 'protocol',
                     'Optional (defaults to udp). Defines which transport protocol to listen for syslog messages on. '
                     'Valid values can be \'udp\' or \'tcp\', which can be combined with a comma to specify both, e.g. \'udp, tcp',
                     convert_to=str, default='udp')

define_config_option( __monitor__, 'udp_port',
                     'Optional (defaults to 514). Defines which port to listen for udp syslog messages on. '
                     'Note: ports lower than 1024 require the agent to run with root privileges. '
                     'Not used if ``protocol`` does not specify udp',
                     default=514, min_value=1, max_value=65535, convert_to=int)

define_config_option( __monitor__, 'tcp_port',
                     'Optional (defaults to 6514). Defines which port to listen for udp syslog messages on. '
                     'Not used if ``protocol`` does not specify tcp',
                     default=6514, min_value=1, max_value=65535, convert_to=int)



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
        SocketServer.UDPServer.__init__( self, address, SyslogUDPHandler )

class SyslogTCPServer( SocketServer.ThreadingMixIn, SocketServer.TCPServer ):
    """Class that creates a TCP SocketServer on a specified port
    """
    def __init__( self, port ):
        address = ( 'localhost', port )
        SocketServer.TCPServer.__init__( self, address, SyslogTCPHandler )

class SyslogHandler:
    """Protocol neutral class for handling messages that come in from a syslog server
    """
    def __init__( self, logger ):
        self.__logger = logger

    def handle( self, data ):
        self.__logger.emit_value( "message", data )

class SyslogServer:
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures handlers to process messages.

    This removes the need for users of this class to care about the underlying protocol being used
    """
    def __init__( self, protocol, config, logger ):
        server = None
        try:
            port = 0
            if protocol == 'tcp':
                port = config.get( 'tcp_port' )
                server = SyslogTCPServer( port )
            elif protocol == 'udp':
                port = config.get( 'udp_port' )
                server = SyslogUDPServer( port )

        except socket_error as e:
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

        self.__server = server
        self.__thread = None

    def start( self, run_state ):
        if run_state != None:
            run_state.register_on_stop_callback( self.__server.shutdown )

        self.__server.serve_forever()

    def start_threaded( self, run_state ):
        self.__thread = StoppableThread( target=self.start, name="Syslog monitor thread for %s" % self.__server.syslog_transport_protocol )
        self.__thread.start()

    def stop( self, wait_on_join=True, join_timeout=5 ):
        if self.__thread != None:
            self.__thread.stop( wait_on_join=wait_on_join, join_timeout=join_timeout )


class SyslogMonitor( ScalyrMonitor ):
    """Monitor plugin for syslog messages

    This plugin listens on one or more ports/protocols for syslog messages, and uploads them
    to Scalyr servers.
    """
    def _initialize( self ):

        #the main server
        self.__server = None

        #any extra servers if we are listening for multiple protocols
        self.__extra_servers = []

        #get a list of protocols from the protocol option
        protocol_string = self._config.get( 'protocol' )
        self.__protocol_list = [p.strip().lower() for p in protocol_string.split(',')]

        if len( self.__protocol_list ) == 0:
            raise Exception('Invalid config state for Syslog Monitor. '
                            'No protocols specified')

        allowed_protocols = [ 'tcp', 'udp' ]

        for p in self.__protocol_list:
            if p not in allowed_protocols:
                raise Exception( 'Unknown value \'%s\' specified for SyslogServer \'protocol\'.' % protocol )

    def run( self ):

        try:
            #create the main server from the first item in the protocol list
            self.__server = SyslogServer( self.__protocol_list[0], self._config, self._logger )

            #iterate over the remaining items creating servers for each protocol
            for p in self.__protocol_list[1:]:
                server = SyslogServer( p, self._config, self._logger )
                self.__extra_servers.append( server )

            #start any extra servers in their own threads
            for server in self.__extra_servers:
                server.start_threaded( self._run_state )

            #start the main server
            self.__server.start( self._run_state )
        except Exception as e:
            self._logger.exception('Monitor died due to exception:', error_code='failedMonitor')

    def stop(self, wait_on_join=True, join_timeout=5):

        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        #stop any extra servers
        for server in self.__extra_servers:
            server.stop( wait_on_join, join_timeout )

