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
#
# author: Imron Alston <imron@imralsoftware.com>

__author__ = 'imron@imralsoftware.com'

import time
import sys
import socket
import unittest
import logging
from cStringIO import StringIO

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogMonitor

import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.util import StoppableThread

class SyslogMonitorTestCase( unittest.TestCase ):
    def assertNoException( self, func ):
        try:
            func()
        except Exception, e:
            self.fail( "Unexpected Exception: %s" % str( e )  )
        except:
            self.fail( "Unexpected Exception: %s" % sys.exc_info()[0]  )

class SyslogMonitorConfigTest( SyslogMonitorTestCase ):

    def test_config_protocol_udp( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'udp'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_udp_upper( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'UDP'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_tcp( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'tcp'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_tcp_upper( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'TCP'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_multiple( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'tcp, udp'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_multiple_with_ports( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'tcp:4096, udp:5082'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_multiple( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'tcp, udp'
        }
        self.assertNoException( lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_invalid( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'XXX'
        }
        self.assertRaises( Exception, lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_protocol_empty( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': ''
        }
        self.assertRaises( Exception, lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )

    def test_config_port_too_high( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'udp:70000'
        }
        self.assertRaises( Exception, lambda: SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) ) )


class SyslogMonitorConnectTest( SyslogMonitorTestCase ):

    def setUp( self ):
        self.monitor = None
        self.sockets = []

        #capture log output
        scalyr_logging.set_log_destination(use_stdout=True)
        scalyr_logging.set_log_level(scalyr_logging.DEBUG_LEVEL_0)
        self.logger = scalyr_logging.getLogger( "syslog_monitor[test]" )
        self.logger.setLevel( logging.INFO )
        self.stream = StringIO();
        self.handler = logging.StreamHandler( self.stream )
        self.logger.addHandler( self.handler )

        #hide stdout
        self.old = sys.stdout
        sys.stdout = StringIO()

    def tearDown( self ):
        #close any open sockets
        for s in self.sockets:
            s.close()

        #stop any running monitors - this might be open if an exception was thrown before a test called monitor.stop()
        if self.monitor != None:
            self.monitor.stop()

        self.logger.removeHandler( self.handler )
        self.handler.close()

        #restore stdout
        sys.stdout.close()
        sys.stdout = self.old


    def test_run_tcp_server( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'tcp',
        }

        self.monitor = SyslogMonitor( config, self.logger )
        self.monitor.open_metric_log()

        self.monitor.start()
        s = socket.socket()
        self.sockets.append( s )

        expected = "TCP Test"
        s.connect( ('localhost', 6514 ) )
        s.send( expected )

        self.monitor.stop()
        self.monitor = None

        self.handler.flush()
        actual = self.stream.getvalue().strip()

        self.assertTrue( expected in actual, "Unable to find '%s' in output:\n\t %s" % (expected, actual)  )


    def test_run_udp_server( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'udp:5514',
        }
        self.monitor = SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) )
        self.monitor.open_metric_log()
        self.monitor.start()

        s = socket.socket( socket.AF_INET, socket.SOCK_DGRAM )
        self.sockets.append( s )

        expected = "UDP Test"
        s.sendto( expected, ('localhost', 5514) )

        self.monitor.stop()
        self.monitor = None

        self.handler.flush()
        actual = self.stream.getvalue().strip()

        self.assertTrue( expected in actual, "Unable to find '%s' in output:\n\t %s" % (expected, actual)  )

    def test_run_multiple_servers( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocol': 'udp:8000, tcp:8001, udp:8002, tcp:8003',
        }
        self.monitor = SyslogMonitor( config, scalyr_logging.getLogger( "syslog_monitor[test]" ) )
        self.monitor.open_metric_log()
        self.monitor.start()

        #sleep to make sure all the server threads have started
        time.sleep( 0.001 )

        udp = socket.socket( socket.AF_INET, socket.SOCK_DGRAM )
        self.sockets.append( udp )

        tcp1 = socket.socket()
        self.sockets.append( tcp1 )

        tcp2 = socket.socket()
        self.sockets.append( tcp2 )

        expected_udp1 = "UDP Test"
        udp.sendto( expected_udp1, ('localhost', 8000) )

        expected_udp2 = "UDP2 Test"
        udp.sendto( expected_udp2, ('localhost', 8002) )

        expected_tcp1 = "TCP Test"
        tcp1.connect( ('localhost', 8001 ) )
        tcp1.send( expected_tcp1 )

        expected_tcp2 = "TCP2 Test"
        tcp2.connect( ('localhost', 8003) )
        tcp2.send( expected_tcp2 )

        self.monitor.stop()
        self.monitor = None

        self.handler.flush()
        actual = self.stream.getvalue().strip()

        self.assertTrue( expected_udp1 in actual, "Unable to find '%s' in output:\n\t %s" % (expected_udp1, actual)  )
        self.assertTrue( expected_udp2 in actual, "Unable to find '%s' in output:\n\t %s" % (expected_udp2, actual)  )
        self.assertTrue( expected_tcp1 in actual, "Unable to find '%s' in output:\n\t %s" % (expected_tcp1, actual)  )
        self.assertTrue( expected_tcp2 in actual, "Unable to find '%s' in output:\n\t %s" % (expected_tcp2, actual)  )



