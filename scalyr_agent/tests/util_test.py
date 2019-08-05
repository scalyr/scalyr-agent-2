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
from mock import patch
import struct
import threading
from mock import patch, MagicMock

import scalyr_agent.util as scalyr_util

from scalyr_agent.util import JsonReadFileException, RateLimiter, BlockingRateLimiter, FakeRunState, ScriptEscalator
from scalyr_agent.util import StoppableThread, RedirectorServer, RedirectorClient, RedirectorError
from scalyr_agent.util import verify_and_get_compress_func
from scalyr_agent.json_lib import JsonObject

from scalyr_agent.test_base import ScalyrTestCase


class TestUtilCompression(ScalyrTestCase):
    def setUp(self):
        self._data = 'The rain in spain. ' * 1000

    def test_zlib(self):
        """Successful zlib compression"""
        data = self._data
        compress = verify_and_get_compress_func('deflate')
        import zlib
        self.assertEqual(data, zlib.decompress(compress(data)))

    def test_bz2(self):
        """Successful bz2 compression"""
        data = self._data
        compress = verify_and_get_compress_func('bz2')
        import bz2
        self.assertEqual(data, bz2.decompress(compress(data)))

    def test_bad_compression_type(self):
        """User enters unsupported compression type"""
        self.assertIsNone(verify_and_get_compress_func('bad_compression_type'))

    def test_bad_compression_lib_exception_on_import(self):
        """Pretend that import bz2/zlib raises exception"""

        def _mock_get_compress_module(compression_type):
            raise Exception('Mimic exception when importing compression lib')

        @patch('scalyr_agent.util.get_compress_module', new=_mock_get_compress_module)
        def _test(compression_type):
            self.assertIsNone(verify_and_get_compress_func(compression_type))

        _test('deflate')
        _test('bz2')

    def test_bad_compression_lib_no_compression(self):
        """Pretend that the zlib/bz2 library compress() method doesn't perform any comnpression"""

        def _mock_get_compress_module(compression_type):
            m = MagicMock()
            # simulate module.compress() method that does not compress input data string
            m.compress = lambda data, compression_level: data
            return m

        @patch('scalyr_agent.util.get_compress_module', new=_mock_get_compress_module)
        def _test(compression_type):
            self.assertIsNone(verify_and_get_compress_func(compression_type))

        _test('deflate')
        _test('bz2')



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

    def test_is_list_of_strings_yes( self ):
        self.assertTrue( scalyr_util.is_list_of_strings( [ '*', 'blah', 'dah' ] ) )

    def test_is_list_of_strings_no( self ):
        self.assertFalse( scalyr_util.is_list_of_strings( [ '*', 3, { 'blah': 'dah' } ] ) )

    def test_is_list_of_strings_none( self ):
        self.assertFalse( scalyr_util.is_list_of_strings( None ) )


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
        # Since the ScalyrTestCase sets the name prefix, we need to set it back to None to get an unmolested name.
        StoppableThread.set_name_prefix(None)
        test_thread = StoppableThread('Testing', self._run_method)
        self.assertEqual(test_thread.getName(), 'Testing')
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_name_prefix(self):
        StoppableThread.set_name_prefix('test_name_prefix: ')
        test_thread = StoppableThread('Testing', self._run_method)
        self.assertEqual(test_thread.getName(), 'test_name_prefix: Testing')
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_name_prefix_with_none(self):
        StoppableThread.set_name_prefix('test_name_prefix: ')
        test_thread = StoppableThread(target=self._run_method)
        self.assertEqual(test_thread.getName(), 'test_name_prefix: ')
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


def always_true():
    while True:
        yield True

def always_false():
    while True:
        yield False


def rate_maintainer(consecutive_success_threshold, backoff_rate, increase_rate):
    """Returns a generator that maintains the rate at a constant level by balancing failures with successes
    """
    last = True
    consecutive_true = 0
    backoff_increase_ratio = float(backoff_rate) * increase_rate
    required_consecutive_successes = int(consecutive_success_threshold * backoff_increase_ratio)

    while True:
        if last:
            if consecutive_true == required_consecutive_successes:
                last = False
                consecutive_true = 0
            else:
                # stay True
                consecutive_true += 1
        else:
            last = True
            consecutive_true += 1
        yield last


class BlockingRateLimiterTest(ScalyrTestCase):

    def setUp(self):
        self._fake_clock = scalyr_util.FakeClock()

    def __test_rate_adjustment(self):

        rl = BlockingRateLimiter(
            num_agents=1,
            initial_cluster_rate=10.0,
            max_cluster_rate=100.0,
            min_cluster_rate=1.0,
            consecutive_success_threshold=5,
            strategy=BlockingRateLimiter.STRATEGY_MULTIPLY,
            increase_factor=2.0,
            backoff_factor=0.5,
            max_concurrency=1,
            fake_clock=self._fake_clock
        )

        @patch.object(rl, '_get_next_ripe_time')
        def simulate_very_fast_actual_rate(mock_rate_limiter):
            """Simulate number of required successes one short of what's required to alter the rate"""

            # make the rate limiter choose very small increments between token grants
            def mock_get_next_ripe_time(*args, **kwargs):
                self._fake_clock.advance_time(0.00000000000001)
            mock_rate_limiter.side_effect = mock_get_next_ripe_time

            rl.acquire_token()
            for x in range(4):
                rl.release_token(True)
                rl.acquire_token()

            old_rate = rl._current_cluster_rate
            # actual rate would always be high because of simulated short times between token grants
            self.assertGreater(rl._get_actual_cluster_rate(), old_rate)
            rl.release_token(True)
            # assert that the new rate is no higher than old rate x 2
            self.assertEqual(rl._current_cluster_rate, 2.0 * old_rate)
        simulate_very_fast_actual_rate()


    def test_fixed_rate_single_concurrency(self):
        """Longer experiment"""
        # 1 rps x 1000 simulated seconds => 1000 increments
        self._test_fixed_rate(desired_agent_rate=1.0, experiment_duration=10000, concurrency=1, expected_requests=10000,
                              allowed_variance=(0.95, 1.05))

    def test_fixed_rate_multiple_concurrency(self):
        """Multiple clients should not affect overall rate"""
        # 1 rps x 100 simulated seconds => 100 increments
        # Higher concurrency has more variance
        self._test_fixed_rate(desired_agent_rate=1.0, experiment_duration=10000, concurrency=3, expected_requests=10000,
                              allowed_variance=(0.8, 1.2))

    def _test_fixed_rate(self, desired_agent_rate, experiment_duration, concurrency, expected_requests, allowed_variance):
        """A utility pass-through that fixes the initial, upper and lower rates"""
        num_agents = 1000
        cluster_rate = num_agents * desired_agent_rate
        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=cluster_rate, max_cluster_rate=cluster_rate, min_cluster_rate=cluster_rate,
            consecutive_success_threshold=5, experiment_duration=experiment_duration, max_concurrency=concurrency,
            expected_requests=expected_requests, allowed_variance=allowed_variance
        )

    def test_variable_rate_single_concurrency_all_successes(self):
        """Rate should quickly max out at max_cluster_rate"""

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 1000
        concurrency = 1
        max_rate_multiplier = 10

        # Expected behavior (saturates at upper rate given all successes)
        expected_requests = max_rate_multiplier * experiment_duration
        allowed_variance = (0.8, 1.2)

        # Derived values
        num_agents = 10
        initial_cluster_rate = num_agents * initial_agent_rate
        max_cluster_rate = max_rate_multiplier * initial_cluster_rate

        self._test_rate_limiter(
            num_agents=10,
            initial_cluster_rate=initial_cluster_rate, max_cluster_rate=max_cluster_rate, min_cluster_rate=0,
            experiment_duration=experiment_duration, max_concurrency=concurrency,
            consecutive_success_threshold=5, increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests, allowed_variance=allowed_variance,
        )

    def test_variable_rate_single_concurrency_all_failures(self):
        """Rate should quickly decrease to min_cluster_rate"""

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 1000000
        concurrency = 1
        min_rate_multiplier = 0.01  # min rate should be at least an order of magnitude lower than initial rate.

        # Expected behavior
        expected_requests = min_rate_multiplier * experiment_duration
        allowed_variance = (0.8, 1.2)

        # Derived values
        num_agents = 10
        initial_cluster_rate = num_agents * initial_agent_rate
        max_cluster_rate = initial_cluster_rate
        min_cluster_rate = min_rate_multiplier * initial_cluster_rate

        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_cluster_rate,
            min_cluster_rate=min_cluster_rate,
            experiment_duration=experiment_duration,
            max_concurrency=concurrency,
            consecutive_success_threshold=5,
            increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests,
            allowed_variance=allowed_variance,
            reported_outcome_generator=always_false(),
        )

    def test_variable_rate_single_concurrency_push_pull(self):
        """Rate should fluctuate closely around initial rate because of equal successes/failures"""

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 10000
        concurrency = 1
        min_rate_multiplier = 0.1
        max_rate_multiplier = 10
        consecutive_success_threshold = 5
        backoff_factor = 0.5
        increase_factor = 2.0

        # Expected behavior
        # 1 * 1 rps * 100s
        expected_requests = 1 * experiment_duration
        allowed_variance = (0.8, 1.2)  # variance increases as difference between backoffs increase

        # Derived values
        num_agents = 100
        initial_cluster_rate = num_agents * initial_agent_rate

        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_rate_multiplier * initial_cluster_rate,
            min_cluster_rate=min_rate_multiplier * initial_cluster_rate,
            experiment_duration=experiment_duration,
            max_concurrency=concurrency,
            consecutive_success_threshold=consecutive_success_threshold,
            increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests,
            allowed_variance=allowed_variance,
            reported_outcome_generator=rate_maintainer(consecutive_success_threshold, backoff_factor, increase_factor),
            backoff_factor=backoff_factor,
            increase_factor=increase_factor,
        )

    def _test_rate_limiter(
        self, num_agents, consecutive_success_threshold, initial_cluster_rate, max_cluster_rate, min_cluster_rate,
        experiment_duration, max_concurrency, expected_requests, allowed_variance,
        reported_outcome_generator=always_true(),
        increase_strategy=BlockingRateLimiter.STRATEGY_MULTIPLY,
        backoff_factor=0.5, increase_factor=2.0,
    ):
        """Main test logic that runs max_concurrency client threads for a defined experiment duration.
        
        The experiment is driven off a fake_clock (so it can complete in seconds, not minutes or hours).
        
        Each time a successful acquire() completes, a counter is incremented.  At experiment end, this counter
        should be close enough to a calculated expected value, based on the specified rate.
        
        Concurrency should not affect the overall rate of allowed acquisitions.
        
        The reported outcome by acquiring clients is determined by invoking the callable `reported_outcome_callable`.


        @param num_agents: Num agents in cluster (to derive agent rate from cluster rate)
        @param consecutive_success_threshold: 
        @param initial_cluster_rate: Initial cluster rate
        @param max_cluster_rate:  Upper bound on cluster rate
        @param min_cluster_rate: Lower bound on cluster rate
        @param increase_strategy: Strategy for increasing rate
        @param experiment_duration: Experiment duration in seconds
        @param max_concurrency: Number of tokens to create
        @param expected_requests: Expected number of requests at the end of experiment
        @param allowed_variance: Allowed variance between expected and actual number of requests. (e.g. 0.1 = 10%)
        @param reported_outcome_generator: Generator to get reported outcome boolean value
        @param fake_clock_increment: Fake clock increment by (seconds)
        """
        rate_limiter = BlockingRateLimiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_cluster_rate,
            min_cluster_rate=min_cluster_rate,
            consecutive_success_threshold=consecutive_success_threshold,
            strategy=increase_strategy,
            increase_factor=increase_factor,
            backoff_factor=backoff_factor,
            max_concurrency=max_concurrency,
            fake_clock=self._fake_clock,
        )

        test_state = {
            'count': 0,
            'times': [],
        }
        test_state_lock = threading.Lock()
        outcome_generator_lock = threading.Lock()
        experiment_end_time = self._fake_clock.time() + experiment_duration

        def consume_token_blocking():
            """Client threads will keep acquiring tokens until experiment end time"""
            while self._fake_clock.time() < experiment_end_time:
                # A simple loop that acquires token, updates a counter, then releases token with an outcome
                # provided by reported_outcome_generator()
                t1 = self._fake_clock.time()
                token = rate_limiter.acquire_token()
                # update test state
                test_state_lock.acquire()
                try:
                    test_state['count'] += 1
                    test_state['times'].append(int(t1))
                finally:
                    test_state_lock.release()

                outcome_generator_lock.acquire()
                try:
                    outcome = reported_outcome_generator.next()
                    rate_limiter.release_token(token, outcome)
                finally:
                    outcome_generator_lock.release()

        threads = [threading.Thread(target=consume_token_blocking) for _ in range(max_concurrency)]
        [t.setDaemon(True) for t in threads]
        [t.start() for t in threads]

        at_least_one_client_thread_incomplete = True
        while at_least_one_client_thread_incomplete:
            # All client threads are likely blocking on the token queue at this point
            # The experiment will never start until at least one token is granted (and waiting threads notified)
            # To jump start this, simply advance fake clock to the ripe_time.
            self._fake_clock.advance_time(increment_by=rate_limiter._ripe_time - self._fake_clock.time())
            # Wake up after 1 second just in case and trigger another advance
            [t.join(1) for t in threads]
            at_least_one_client_thread_incomplete = False
            for t in threads:
                if t.isAlive():
                    at_least_one_client_thread_incomplete = True
                    break

        test_state_lock.acquire()
        try:
            requests = test_state['count']
        finally:
            test_state_lock.release()

        print(requests)
        print(test_state['times'])

        # Assert that count is close enough to the expected count
        observed_ratio = float(requests) / expected_requests
        self.assertGreater(observed_ratio, allowed_variance[0])
        self.assertLess(observed_ratio, allowed_variance[1])
