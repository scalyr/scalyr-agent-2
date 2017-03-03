# Copyright 2017 Scalyr Inc.
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
# author: Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import time
import sys
import unittest

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogRequestParser

class Handler( object ):
    def __init__( self ):
        self.values = []

    def handle( self, message ):
        self.values.append( message )

class SyslogRequestParserTestCase( unittest.TestCase ):

    def test_framed_messages( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()

        parser.process( "5 hello5 world", handler.handle )

        self.assertEqual( 2, len( handler.values ) )
        self.assertEqual( "hello", handler.values[0] )
        self.assertEqual( "world", handler.values[1] )

    def test_framed_message_incomplete( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()

        parser.process( "11 hello", handler.handle )

        self.assertEqual( 0, len( handler.values ) )

        parser.process( " world", handler.handle )

        self.assertEqual( 1, len( handler.values ) )
        self.assertEqual( "hello world", handler.values[0] )

    def test_framed_message_multiple_incomplete( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()

        parser.process( "11 hello", handler.handle )

        self.assertEqual( 0, len( handler.values ) )
        parser.process( " w", handler.handle )

        self.assertEqual( 0, len( handler.values ) )
        parser.process( "or", handler.handle )

        self.assertEqual( 0, len( handler.values ) )
        parser.process( "ld", handler.handle )

        self.assertEqual( 1, len( handler.values ) )
        self.assertEqual( "hello world", handler.values[0] )

    def test_framed_message_invalid_frame_size( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()
        self.assertRaises( ValueError, lambda: parser.process( "1a1 hello", handler.handle ) )

    def test_framed_message_exceeds_max_size( self ):
        parser = SyslogRequestParser( None, 11 )
        handler = Handler()
        parser.process( "23 hello world h", handler.handle )
        parser.process( "10 lo world .", handler.handle )

        self.assertEqual( 2, len( handler.values ) )
        self.assertEqual( "23 hello world h", handler.values[0] )
        self.assertEqual( " 10 lo world .", handler.values[1] )

    def test_unframed_messages( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()
        parser.process( "hello\nworld\n", handler.handle )

        self.assertEqual( 2, len( handler.values ) )
        self.assertEqual( "hello", handler.values[0] )
        self.assertEqual( "world", handler.values[1] )

    def test_unframed_messages_incomplete( self ):
        parser = SyslogRequestParser( None, 32 )
        handler = Handler()

        parser.process( "hello", handler.handle )
        self.assertEqual( 0, len( handler.values ) )

        parser.process( " world\n", handler.handle )

        self.assertEqual( 1, len( handler.values ) )
        self.assertEqual( "hello world", handler.values[0] )

    def test_unframed_message_exceeds_max_size( self ):
        parser = SyslogRequestParser( None, 13 )
        handler = Handler()

        parser.process( "in my hand i have ", handler.handle )
        self.assertEqual( 1, len( handler.values ) )
        self.assertEqual( "in my hand i have ", handler.values[0] )
        parser.process( "100 dollars\n", handler.handle )
        self.assertEqual( 2, len( handler.values ) )
        self.assertEqual( "100 dollars", handler.values[1] )


