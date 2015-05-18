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
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import socket
import struct
import cStringIO

from scalyr_agent.monitor_utils.server_processors import RequestStream, ConnectionProcessor
from scalyr_agent.monitor_utils.server_processors import Int32RequestParser, LineRequestParser
from scalyr_agent.monitor_utils.server_processors import ConnectionIdleTooLong, RequestSizeExceeded
from scalyr_agent.util import FakeRunState
from scalyr_agent.test_base import ScalyrTestCase


class TestInt32RequestParser(ScalyrTestCase):
    def setUp(self):
        self.__buffer = cStringIO.StringIO()

    def test_basic_case(self):
        self.assertEquals(self.run_test_case('Hi there', 8), 'Hi there')
        self.assertEquals(self.run_test_case('Hi thereok', 8), 'Hi there')

    def test_prefix_not_ready(self):
        self.assertIsNone(self.run_test_case('Hi there', 8, truncate_size=2))

    def test_body_not_ready(self):
        self.assertIsNone(self.run_test_case('Hi there', 8, truncate_size=8))

    def test_request_too_long(self):
        self.assertRaises(RequestSizeExceeded, self.run_test_case, 'Hi there fool again', 18)

    def run_test_case(self, input_string, length_to_send, truncate_size=None):
        input_buffer = cStringIO.StringIO()
        input_buffer.write(struct.pack('!I', length_to_send))
        input_buffer.write(input_string)
        if truncate_size is not None:
            input_buffer.truncate(truncate_size)
        num_bytes = input_buffer.tell()
        input_buffer.seek(0)

        result = Int32RequestParser(10).parse_request(input_buffer, num_bytes)

        if result is None:
            self.assertEquals(0, input_buffer.tell())
        else:
            self.assertEquals(len(result) + struct.calcsize('!I'), input_buffer.tell())
        return result


class FakeSocket(object):
    """An object that implements the socket interface necessary for testing RequestStream."""

    def __init__(self):
        # True if the socket has been closed.
        self.__is_closed = False
        # Holds the fake data that is inserted by the test code and will be return to callers of recv.
        self.__stream = cStringIO.StringIO()

    def recv(self, max_bytes):
        """Reads data from the socket.

        This test object will return the next bytes that were added to this object using
        the add_input method.  If not enough bytes are available, then will raise a timeout.
        If the socket is closed, then returns None.

        @param max_bytes: The maximum number of bytes to return.
        """
        result = self.__stream.read(max_bytes)
        if len(result) == 0:
            if self.__is_closed:
                return None
            else:
                raise socket.timeout()
        return result

    def setblocking(self, is_blocking):
        """Set whether or not the socket is blocking.

        This is provided just because the code being tested needs to invoke it.

        @param is_blocking: Whether or not the socket should be blocking.
        """
        pass

    def add_input(self, string_input):
        """Adds the specified string to the pending input that will be returned by calls to 'recv' on this
        socket.

        Testing code can use this to simulate bytes being received.

        @param string_input: The input.
        """
        # We have to remember our current position in the stream so that we can return here.
        original_position = self.__stream.tell()
        # Go to the end and insert the bytes.
        self.__stream.seek(0, 2)
        self.__stream.write(string_input)
        # Then return.
        self.__stream.seek(original_position)

    def close(self):
        self.__is_closed = True


class TestRequestStream(ScalyrTestCase):
    def setUp(self):
        self.__fake_socket = FakeSocket()
        self.__fake_run_state = FakeRunState()

        parser = LineRequestParser(10)
        self.__request_stream = RequestStream(self.__fake_socket, parser.parse_request, max_buffer_size=10,
                                              max_request_size=10)

    def test_basic_case(self):
        # Basic case of just a single line.
        self.__fake_socket.add_input('Hi there\n')
        self.assertEquals(self.read_request(), 'Hi there\n')
        self.assertEquals(self.total_times_slept(), 1)
        self.assertEquals(self.buffer_size(), 0)

        self.assertIsNone(self.read_request())

    def test_multiple_lines(self):
        self.__fake_socket.add_input('Hi\nBye\nOk\n')
        self.assertEquals(self.read_request(), 'Hi\n')
        self.assertEquals(self.buffer_size(), 10)
        self.assertEquals(self.read_request(), 'Bye\n')
        self.assertEquals(self.read_request(), 'Ok\n')
        self.assertEquals(self.total_times_slept(), 1)
        self.assertEquals(self.buffer_size(), 0)
        self.assertFalse(self.at_end())

        self.assertIsNone(self.read_request())

    def test_broken_lines(self):
        self.__fake_socket.add_input('Hi there')
        self.assertIsNone(self.read_request())
        self.__fake_socket.add_input('\n')
        self.assertEquals(self.read_request(), 'Hi there\n')
        self.assertEquals(self.total_times_slept(), 2)
        self.assertEquals(self.buffer_size(), 0)
        self.assertFalse(self.at_end())

    def test_request_too_long(self):
        self.__fake_socket.add_input('0123456789')
        self.assertRaises(RequestSizeExceeded, self.read_request)
        self.assertFalse(self.at_end())
    
    def test_full_compaction(self):
        self.__fake_socket.add_input('012\n345678')
        self.assertEquals(self.read_request(), '012\n')
        self.assertEquals(self.total_times_slept(), 1)
        self.assertEquals(self.buffer_size(), 10)
        self.assertFalse(self.at_end())

        self.assertIsNone(self.read_request())
        self.assertEquals(self.buffer_size(), 6)

        self.__fake_socket.add_input('\n')
        self.assertEquals(self.read_request(), '345678\n')
        self.assertEquals(self.total_times_slept(), 3)
        self.assertEquals(self.buffer_size(), 0)

    def test_close(self):
        self.__fake_socket.add_input('Hi there\n')
        self.__fake_socket.close()

        self.assertEquals(self.read_request(), 'Hi there\n')
        self.assertEquals(self.total_times_slept(), 1)
        self.assertEquals(self.buffer_size(), 0)
        self.assertIsNone(self.read_request())
        self.assertTrue(self.at_end())
        self.assertEquals(self.total_times_slept(), 2)

    def read_request(self):
        return self.__request_stream.read_request(run_state=self.__fake_run_state)

    def total_times_slept(self):
        return self.__fake_run_state.total_times_slept

    def buffer_size(self):
        return self.__request_stream.get_buffer_size()

    def at_end(self):
        return self.__request_stream.at_end()

class TestLineRequestEOF( ScalyrTestCase ):
    def setUp(self):
        self.__fake_socket = FakeSocket()
        self.__fake_run_state = FakeRunState()

        parser = LineRequestParser(100, eof_as_eol=True)
        self.__request_stream = RequestStream(self.__fake_socket, parser.parse_request, max_buffer_size=100,
                                              max_request_size=100)
    def read_request(self):
        return self.__request_stream.read_request(run_state=self.__fake_run_state)

    def test_eof_as_eol( self ):
        self.__fake_socket.add_input('Hi there\nGoodbye')
        self.assertEquals(self.read_request(), 'Hi there\n')
        self.assertEquals( self.read_request(), 'Goodbye' )


class TestConnectionHandler(ScalyrTestCase):
    def setUp(self):
        self.__fake_socket = FakeSocket()
        self.__fake_run_state = FakeRunState()
        self.__last_request = None

        parser = LineRequestParser(10)
        request_stream = RequestStream(self.__fake_socket, parser.parse_request, max_buffer_size=10,
                                       max_request_size=10)

        self.__fake_handler = ConnectionProcessor(request_stream, self.execute_request, self.__fake_run_state, 5.0)
        self.__fake_time = 0.0

    def test_basic_case(self):
        self.__fake_socket.add_input('Hi there\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, 'Hi there\n')

    def test_multiple_requests(self):
        self.__fake_socket.add_input('Hi there\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, 'Hi there\n')

        self.advance_time(3.0)
        self.__fake_socket.add_input('2nd there\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, '2nd there\n')

        self.advance_time(3.0)
        self.assertTrue(self.run_single_cycle())
        self.assertIsNone(self.__last_request)

    def test_inactivity_error(self):
        self.__fake_socket.add_input('Hi there\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, 'Hi there\n')

        self.advance_time(3.0)
        self.assertTrue(self.run_single_cycle())
        self.assertIsNone(self.__last_request)

        self.advance_time(3.0)
        self.assertRaises(ConnectionIdleTooLong, self.run_single_cycle)

    def test_run_state_done(self):
        self.__fake_socket.add_input('Hi there\nOk\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, 'Hi there\n')
        self.__fake_run_state.stop()

        self.assertFalse(self.run_single_cycle())
        self.assertIsNone(self.__last_request)

    def test_connection_closed(self):
        self.__fake_socket.add_input('Hi there\n')
        self.assertTrue(self.run_single_cycle())
        self.assertEquals(self.__last_request, 'Hi there\n')
        self.__fake_socket.close()

        self.assertFalse(self.run_single_cycle())
        self.assertIsNone(self.__last_request)

    def execute_request(self, request):
        self.__last_request = request

    def run_single_cycle(self):
        self.__last_request = None
        return self.__fake_handler.run_single_cycle(current_time=self.__fake_time)

    def advance_time(self, delta):
        self.__fake_time += delta

