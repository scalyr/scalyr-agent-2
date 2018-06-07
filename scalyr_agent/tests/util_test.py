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

import datetime
import os
import tempfile
import unittest
import struct
import threading

import scalyr_agent.util as scalyr_util

from scalyr_agent.util import JsonReadFileException, RateLimiter, FakeRunState, ScriptEscalator
from scalyr_agent.util import StoppableThread, RedirectorServer, RedirectorClient, RedirectorError
from scalyr_agent.json_lib import JsonObject

from scalyr_agent.test_base import ScalyrTestCase

class TestUtil(ScalyrTestCase):

    def setUp(self):
        self.__tempdir = tempfile.mkdtemp()
        self.__path = os.path.join(self.__tempdir, 'testing.json')

    def test_read_file_as_json(self):
        self.__create_file(self.__path, '{ a: "hi"}')

        json_object = scalyr_util.read_file_as_json(self.__path)
        self.assertEquals(json_object, JsonObject(a='hi'))

    def test_read_file_as_json_no_file(self):
        self.assertRaises(JsonReadFileException, scalyr_util.read_file_as_json, 'foo')

    def test_read_file_as_json_with_bad_json(self):
        self.__create_file(self.__path, '{ a: hi}')

        self.assertRaises(JsonReadFileException, scalyr_util.read_file_as_json, self.__path)

    def test_atomic_write_dict_as_json_file(self):
        info = { 'a': "hi" }
        scalyr_util.atomic_write_dict_as_json_file( self.__path, self.__path + '~', info )

        json_object = scalyr_util.read_file_as_json( self.__path )
        self.assertEquals( json_object, JsonObject( a='hi' ) )

    def __create_file(self, path, contents):
        fp = open(path, 'w')
        fp.write(contents)
        fp.close()

    def test_seconds_since_epoch( self ):
        dt = datetime.datetime( 2015, 8, 6, 14, 40, 56 )
        expected = 1438872056.0
        actual = scalyr_util.seconds_since_epoch( dt )
        self.assertEquals( expected, actual )

    def test_microseconds_since_epoch( self ):
        dt = datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 )
        expected = 1438872056123456
        actual = scalyr_util.microseconds_since_epoch( dt )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_datetime( self ):
        s = "2015-08-06T14:40:56.123456Z"
        expected =  datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 )
        actual = scalyr_util.rfc3339_to_datetime( s )

        self.assertEquals( expected, actual )

    def test_rfc3339_to_datetime_truncated_nano( self ):
        s = "2015-08-06T14:40:56.123456789Z"
        expected =  datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 )
        actual = scalyr_util.rfc3339_to_datetime( s )

        self.assertEquals( expected, actual )

    def test_rfc3339_to_datetime_bad_format_date_and_time_separator( self ):
        s = "2015-08-06 14:40:56.123456789Z"
        expected = None
        actual = scalyr_util.rfc3339_to_datetime( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_datetime_bad_format_has_timezone( self ):
        # currently this function only handles UTC.  Remove this test if
        # updated to be more flexible
        s = "2015-08-06T14:40:56.123456789+04:00"
        expected = None
        actual = scalyr_util.rfc3339_to_datetime( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch( self ):
        s = "2015-08-06T14:40:56.123456Z"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 ) ) * 1000
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch_no_fractions( self ):
        s = "2015-08-06T14:40:56"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2015, 8, 6, 14, 40, 56) ) * 1000
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch_some_fractions( self ):
        s = "2015-08-06T14:40:56.123Z"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2015, 8, 6, 14, 40, 56, 123000 ) ) * 1000
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch_many_fractions( self ):
        s = "2015-08-06T14:40:56.123456789Z"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 ) ) * 1000 + 789
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch_too_many_fractions( self ):
        s = "2015-08-06T14:40:56.123456789999Z"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2015, 8, 6, 14, 40, 56, 123456 ) ) * 1000 + 789
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_rfc3339_to_nanoseconds_since_epoch_strange_value( self ):
        s = "2017-09-20T20:44:00.123456Z"
        expected =  scalyr_util.microseconds_since_epoch( datetime.datetime( 2017, 9, 20, 20, 44, 00, 123456 ) ) * 1000
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch( s )
        self.assertEquals( expected, actual )

    def test_uuid(self):
        first = scalyr_util.create_unique_id()
        second = scalyr_util.create_unique_id()
        self.assertTrue(len(first) > 0)
        self.assertTrue(len(second) > 0)
        self.assertNotEqual(first, second)

    def test_remove_newlines_and_truncate(self):
        self.assertEquals(scalyr_util.remove_newlines_and_truncate('hi', 1000), 'hi')
        self.assertEquals(scalyr_util.remove_newlines_and_truncate('ok then', 2), 'ok')
        self.assertEquals(scalyr_util.remove_newlines_and_truncate('o\nk\n', 1000), 'o k ')
        self.assertEquals(scalyr_util.remove_newlines_and_truncate('ok\n\r there', 1000), 'ok   there')
        self.assertEquals(scalyr_util.remove_newlines_and_truncate('ok\n\r there', 6), 'ok   t')


class TestRateLimiter(ScalyrTestCase):
    def setUp(self):
        self.__test_rate = RateLimiter(100, 10, current_time=0)
        self.__current_time = 0

    def advance_time(self, delta):
        self.__current_time += delta

    def charge_if_available(self, num_bytes):
        return self.__test_rate.charge_if_available(num_bytes, current_time=self.__current_time)

    def test_basic_use(self):
        self.assertTrue(self.charge_if_available(20))
        self.assertTrue(self.charge_if_available(80))
        self.assertFalse(self.charge_if_available(1))

    def test_refill(self):
        self.assertTrue(self.charge_if_available(60))
        self.assertFalse(self.charge_if_available(60))
        self.advance_time(1)
        self.assertFalse(self.charge_if_available(60))
        self.advance_time(1)
        self.assertTrue(self.charge_if_available(60))


class TestRunState(ScalyrTestCase):

    def test_basic_use(self):
        # We use a FakeRunState for testing just so we do not accidentally sleep.
        run_state = FakeRunState()

        self.assertTrue(run_state.is_running())
        run_state.sleep_but_awaken_if_stopped(1.0)
        self.assertEquals(run_state.total_times_slept, 1)
        run_state.stop()
        self.assertFalse(run_state.is_running())

    def test_sleeping_already_stopped(self):
        run_state = FakeRunState()

        run_state.stop()
        run_state.sleep_but_awaken_if_stopped(1.0)
        self.assertEquals(run_state.total_times_slept, 0)

    def test_callbacks(self):
        self.called = False

        def on_stop():
            self.called = True

        run_state = FakeRunState()
        run_state.register_on_stop_callback(on_stop)
        run_state.stop()

        self.assertTrue(self.called)

        # Make sure it is immediately invoked if already stopped.
        self.called = False
        run_state.register_on_stop_callback(on_stop)
        self.assertTrue(self.called)


class TestStoppableThread(ScalyrTestCase):
    def setUp(self):
        self._run_counter = 0

    def test_basic_use(self):
        test_thread = StoppableThread('Testing', self._run_method)
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_basic_extending(self):
        class TestThread(StoppableThread):
            def __init__(self):
                self.run_counter = 0
                StoppableThread.__init__(self, 'Test thread')

            def run_and_propagate(self):
                self.run_counter += 1
                while self._run_state.is_running():
                    self.run_counter += 1
                    self._run_state.sleep_but_awaken_if_stopped(0.03)

        test_thread = TestThread()
        test_thread.start()
        test_thread.stop()

        self.assertTrue(test_thread.run_counter > 0)

    def test_exception(self):
        class TestException(Exception):
            pass

        def throw_an_exception(run_state):
            run_state.is_running()
            raise TestException()

        test_thread = StoppableThread('Testing', throw_an_exception)
        test_thread.start()

        caught_it = False
        try:
            test_thread.stop()
        except TestException:
            caught_it = True

        self.assertTrue(caught_it)

    def _run_method(self, run_state):
        self._run_counter += 1
        while run_state.is_running():
            self._run_counter += 1
            run_state.sleep_but_awaken_if_stopped(0.03)


class TestScriptEscalator(ScalyrTestCase):
    def test_is_user_change_required(self):
        (test_instance, controller) = self.create_instance('czerwin', 'fileA', 'steve')
        self.assertTrue(test_instance.is_user_change_required())

        (test_instance, controller) = self.create_instance('czerwin', 'fileA', 'czerwin')
        self.assertFalse(test_instance.is_user_change_required())

    def test_change_user_and_rerun_script(self):
        (test_instance, controller) = self.create_instance('czerwin', 'fileA', 'steve')
        self.assertEquals(test_instance.change_user_and_rerun_script('random'), 0)

        self.assertEquals(controller.call_count, 1)
        self.assertEquals(controller.last_call['user'], 'steve')
        self.assertIsNotNone(controller.last_call['script_file'])

    def create_instance(self, current_user, config_file, config_owner):
        controller = TestScriptEscalator.ControllerMock(current_user, config_file, config_owner)
        # noinspection PyTypeChecker
        return ScriptEscalator(controller, config_file, os.getcwd() ), controller

    class ControllerMock(object):
        def __init__(self, running_user, expected_config_file, config_owner):
            self.__running_user = running_user
            self.__expected_config_file = expected_config_file
            self.__config_owner = config_owner
            self.last_call = None
            self.call_count = 0

        def get_current_user(self):
            return self.__running_user

        def get_file_owner(self, config_file_path):
            assert self.__expected_config_file == config_file_path
            if self.__expected_config_file == config_file_path:
                return self.__config_owner
            else:
                return None

        def run_as_user(self, user, script_file_path, script_binary, script_args):
            self.call_count += 1
            self.last_call = {
                'user': user,
                'script_file': script_file_path,
                'script_binary': script_binary,
                'script_args': script_args
            }
            return 0


class TestRedirectorServer(ScalyrTestCase):
    """Tests the RedirectorServer code using fakes for stdout, stderr and the channel.
    """
    def setUp(self):
        # Allows us to watch what bytes are being sent to the client.
        self._channel = FakeServerChannel()
        # Allows us to write bytes to stdout, stderr without them going to the terminal.
        self._sys = FakeSys()
        self._server = RedirectorServer(self._channel, sys_impl=self._sys)

    def test_sending_str(self):
        self._server.start()
        # Verify that the server told the channel to accept the next client connection.
        self.assertEquals(self._channel.accept_count, 1)
        # Simulate writing to stdout.
        self._sys.stdout.write('Testing')
        # Make sure we wrote a message to the channel
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 0)
        self.assertEquals(content, 'Testing')

    def test_sending_unicode(self):
        self._server.start()
        self.assertEquals(self._channel.accept_count, 1)
        self._sys.stdout.write(u'caf\xe9')
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 0)
        self.assertEquals(content, u'caf\xe9')

    def test_sending_to_stderr(self):
        self._server.start()
        self.assertEquals(self._channel.accept_count, 1)
        self._sys.stderr.write('Testing again')
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 1)
        self.assertEquals(content, 'Testing again')

    def test_connection_failure(self):
        # Set the channel to simulate a connection timeout.
        self._channel.timeout_connection = True
        caught_it = False
        try:
            # Make sure that we get an exception.
            self._server.start()
        except RedirectorError:
            caught_it = True
        self.assertTrue(caught_it)

    def _parse_sent_bytes(self, content):
        """Parses the stream id and the actual content from the encoded content string sent by the server.

        @param content: The string sent by the server.
        @type content: str

        @return: A tuple of the stream_id and the actual content encoded in the sent string.
        @rtype: (int,str)
        """
        prefix_code = content[0:4]
        code = struct.unpack('i', prefix_code)[0]
        stream_id = code % 2
        num_bytes = code >> 1

        self.assertEquals(len(content), num_bytes + 4)
        decoded_str = content[4:].decode('utf-8')

        return stream_id, decoded_str


class TestRedirectorClient(ScalyrTestCase):
    """Test the RedirectorClient by faking out the client channel and also the clock.
    """
    def setUp(self):
        self._fake_sys = FakeSys()
        # Since the client is an actual other thread that blocks waiting for input from the server, we have to
        # simulate the time using a fake clock.  That will allow us to wait up the client thread from time to time.
        self._fake_clock = scalyr_util.FakeClock()
        # The fake channel allows us to insert bytes being sent by the server.
        self._client_channel = FakeClientChannel(self._fake_clock)
        self._client = RedirectorClient(self._client_channel, sys_impl=self._fake_sys, fake_clock=self._fake_clock)
        self._client.start()
        # Wait until the client thread begins to block for the initial accept from the server.
        self._fake_clock.block_until_n_waiting_threads(1)

    def tearDown(self):
        if self._client is not None:
            self._client.stop(wait_on_join=False)
            self._fake_clock.advance_time(set_to=59.0)
            self._client.join()

    def test_receiving_str(self):
        # Simulate accepting the connection.
        self._accept_client_connection()
        self._send_to_client(0, 'Testing')
        # Wait until have bytes written to stdout by the client thread.
        self._fake_sys.stdout.wait_for_bytes(1.0)
        self.assertEquals(self._fake_sys.stdout.last_write, 'Testing')

    def test_receiving_unicode(self):
        self._accept_client_connection()
        self._send_to_client(0, u'caf\xe9')
        self._fake_sys.stdout.wait_for_bytes(1.0)
        self.assertEquals(self._fake_sys.stdout.last_write, u'caf\xe9')

    def test_connection_timeout(self):
        # We advance the time past 60 seconds which is the connection time out.
        self._fake_clock.advance_time(set_to=61.0)
        got_it = False
        try:
            # Even though we have not called stop on the thread or the server hasn't closed the connection,
            # we should still see the client thread terminate because of the exception it raises.
            self._client.join()
        except RedirectorError:
            got_it = True
        self._client = None
        self.assertTrue(got_it)

    def test_close_from_server(self):
        self._accept_client_connection()
        self._send_to_client(-1, '')
        # Even though we haven't called stop on the client thread, it should still end because the server sent
        # the signal to stop/close.
        self._client.join()
        self._client = None

    def test_stopped_during_connection(self):
        self._client.stop(wait_on_join=False)
        # We have wake all threads so the client thread will notice its thread has been stopped.
        self._fake_clock.wake_all_threads()
        self._client.join()
        self._client = None

    def test_stopped_during_reading(self):
        self._accept_client_connection()

        self._client.stop(wait_on_join=False)
        # We have wake all threads so the client thread will notice its thread has been stopped.
        self._fake_clock.wake_all_threads()
        self._client.join()
        self._client = None

    def _accept_client_connection(self):
        self._client_channel.simulate_server_connect()

    def _send_to_client(self, stream_id, content):
        encoded_content = unicode(content).encode('utf-8')
        code = len(encoded_content) * 2 + stream_id
        self._client_channel.simulate_server_write(struct.pack('i', code) + encoded_content)


class TestRedirectionService(ScalyrTestCase):
    """Tests both the RedirectorServer and the RedirectorClient communicating together.
    """
    def setUp(self):
        self._client_sys = FakeSys()
        self._server_sys = FakeSys()
        self._fake_clock = scalyr_util.FakeClock()
        self._client_channel = FakeClientChannel(self._fake_clock)
        self._server_channel = FakeServerChannel(self._client_channel)
        self._client = RedirectorClient(self._client_channel, sys_impl=self._client_sys, fake_clock=self._fake_clock)
        self._server = RedirectorServer(self._server_channel, sys_impl=self._server_sys)
        self._client.start()
        self._server.start()

    def test_end_to_end(self):
        self._server_sys.stdout.write('Test full')
        self._server.stop()
        self._client.stop()


class FakeServerChannel(RedirectorServer.ServerChannel):
    """A mock-like object for the ServerChannel that allows us to see if certain methods were invoked and with
    what arguments.
    """
    def __init__(self, client_channel=None):
        # Gives the counts of the various methods.
        self.close_count = 0
        self.accept_count = 0
        self.write_count = 0
        # The last string that was used when invoking `write`.
        self.last_write = None
        # If set to True, when the server invokes `accept_client`, it will simulate a connection timeout.
        self.timeout_connection = False
        # If not None, the fake client channel to send the bytes from `write`.
        self._client_channel = client_channel

    def accept_client(self, timeout=None):
        self.accept_count += 1
        if not self.timeout_connection and self._client_channel is not None:
            self._client_channel.simulate_server_connect()
        return not self.timeout_connection

    def write(self, content):
        self.write_count += 1
        self.last_write = content
        if self._client_channel is not None:
            self._client_channel.simulate_server_write(content)

    def close(self):
        self.close_count += 1


class FakeClientChannel(object):
    """Fakes out the RedirectorClient.ClientChannel interface.

    This allows us to simulate the connection being accepted by the server and bytes being sent by the server.
    """
    def __init__(self, fake_clock):
        self._lock = threading.Lock()
        self._allow_connection = False
        self._pending_content = ''
        self._fake_clock = fake_clock

    def connect(self):
        self._lock.acquire()
        result = self._allow_connection
        self._lock.release()
        return result

    def peek(self):
        self._lock.acquire()
        if self._pending_content is not None:
            bytes_to_read = len(self._pending_content)
        else:
            bytes_to_read = 0
        self._lock.release()
        return bytes_to_read, 0

    def read(self, num_bytes_to_read):
        self._lock.acquire()
        assert num_bytes_to_read <= len(self._pending_content)

        result = self._pending_content[0:num_bytes_to_read]
        self._pending_content = self._pending_content[num_bytes_to_read:]
        self._lock.release()
        return result

    def close(self):
        pass

    def simulate_server_connect(self):
        self._lock.acquire()
        self._allow_connection = True
        self._lock.release()
        self._simulate_busy_loop_advance()

    def simulate_server_write(self, content):
        self._lock.acquire()
        self._pending_content = '%s%s' % (self._pending_content, content)
        self._lock.release()
        self._simulate_busy_loop_advance()

    def _simulate_busy_loop_advance(self):
        self._fake_clock.advance_time(increment_by=0.4)

class FakeSys(object):
    def __init__(self):
        self.stdout = FakeSys.FakeFile()
        self.stderr = FakeSys.FakeFile()

    class FakeFile(object):
        def __init__(self):
            self._condition = threading.Condition()
            self._last_write = None

        def write(self, content):
            self._condition.acquire()
            self._last_write = content
            self._condition.notifyAll()
            self._condition.release()

        @property
        def last_write(self):
            self._condition.acquire()
            result = self._last_write
            self._condition.release()
            return result

        def wait_for_bytes(self, timeout):
            self._condition.acquire()
            self._condition.wait(timeout)
            self._condition.release()
