# Copyright 2015 Scalyr Inc.
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
import unittest
from struct import pack

from scalyr_agent.builtin_monitors.redis_monitor import RedisMonitor
from scalyr_agent.builtin_monitors.redis_monitor import RedisHost

class DummyLogger( object ):
    def __init__( self ):
        self.command = ''

    def emit_value( self, key, value, extra_fields ):
        self.command = extra_fields['command']

class RedisHostTestCase( unittest.TestCase ):

    def setUp( self ):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor'
            }
        self.logger = DummyLogger()
        self.host = RedisHost( 'localhost', 6379, '', 1000 )

        self.entry = { 'command' : '',
                  'start_time' : time.time(),
                  'duration' : 100,
                  'id' : 1
                }


    def test_truncated_utf8_message( self ):
        expected = 'abc... (4 more bytes)'

        self.entry['command'] = pack( '3sB18s', 'abc', 0xce, '... (4 more bytes)' )

        self.host.log_entry( self.logger, self.entry )
        self.assertEquals( expected, self.logger.command )

    def test_non_truncated_utf8_message( self ):

        expected = 'abc... (4 more bytes)'
        self.entry['command'] = 'abc... (4 more bytes)'

        self.host.log_entry( self.logger, self.entry )

        self.assertEquals( expected, self.logger.command )

