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

from __future__ import unicode_literals
from __future__ import absolute_import

from scalyr_agent import compat

__author__ = "czerwin@scalyr.com"

from io import open
import re

from scalyr_agent import scalyr_init

scalyr_init()

import sys
import datetime
import os
import tempfile
import threading
import uuid
import mock
from mock import patch, MagicMock
import six

import scalyr_agent.util as scalyr_util

from scalyr_agent.util import (
    JsonReadFileException,
    RateLimiter,
    FakeRunState,
    ScriptEscalator,
    HistogramTracker,
)
from scalyr_agent.util import (
    StoppableThread,
    RedirectorServer,
    RedirectorClient,
    RedirectorError,
)
from scalyr_agent.util import verify_and_get_compress_func
from scalyr_agent.util import get_compress_and_decompress_func
from scalyr_agent.json_lib import JsonObject


from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf
from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase
from scalyr_agent import scalyr_logging


class TestUtilCompression(ScalyrTestCase):
    def setUp(self):
        super(TestUtilCompression, self).setUp()
        self._data = b"The rain in spain. " * 1000

    def test_compression_none(self):
        data = self._data
        compress = verify_and_get_compress_func("none")
        self.assertIsNotNone(compress)

        self.assertEqual(data, compress(data))

        compress_func, decompress_func = get_compress_and_decompress_func("none")
        self.assertIsNotNone(compress_func)
        self.assertIsNotNone(decompress_func)

        self.assertEqual(data, compress_func(data))
        self.assertEqual(data, decompress_func(data))
        self.assertEqual(data, decompress_func(compress_func(data)))

    def test_zlib(self):
        """Successful zlib compression"""
        data = self._data
        compress = verify_and_get_compress_func("deflate")
        self.assertIsNotNone(compress)
        import zlib

        self.assertEqual(data, zlib.decompress(compress(data)))

    def test_bz2(self):
        """Successful bz2 compression"""
        data = self._data
        compress = verify_and_get_compress_func("bz2")
        self.assertIsNotNone(compress)
        import bz2

        self.assertEqual(data, bz2.decompress(compress(data)))

    @skipIf(sys.version_info < (2, 7, 0), "Skipping Python < 2.7")
    def test_lz4(self):
        data = self._data
        compress = verify_and_get_compress_func("lz4")
        self.assertIsNotNone(compress)

        import lz4.frame as lz4

        self.assertEqual(data, lz4.decompress(compress(data)))

    @skipIf(sys.version_info < (2, 7, 0), "Skipping Python < 2.7")
    def test_zstandard(self):
        data = self._data
        compress = verify_and_get_compress_func("zstandard")
        self.assertIsNotNone(compress)

        import zstandard

        decompressor = zstandard.ZstdDecompressor()

        self.assertEqual(data, decompressor.decompress(compress(data)))

    def test_bad_compression_type(self):
        """User enters unsupported compression type"""
        self.assertIsNone(verify_and_get_compress_func("bad_compression_type"))

    def test_bad_compression_lib_exception_on_import(self):
        """Pretend that import bz2/zlib raises exception"""

        def _mock_get_compress_and_decompress_func(
            compression_type, compression_level=9
        ):
            raise Exception("Mimic exception when importing compression lib")

        @patch(
            "scalyr_agent.util.get_compress_and_decompress_func",
            new=_mock_get_compress_and_decompress_func,
        )
        def _test(compression_type):
            self.assertIsNone(verify_and_get_compress_func(compression_type))

        _test("deflate")
        _test("bz2")
        _test("lz4")
        _test("zstandard")

    def test_bad_compression_lib_no_compression(self):
        """Pretend that the zlib/bz2 library compress() method doesn't perform any comnpression"""

        def _mock_get_compress_and_decompress_func(
            compression_type, compression_level=9
        ):
            m = MagicMock()
            # simulate module.compress() method that does not compress input data string
            m.compress = lambda data, compression_level=9: data
            m.decompress = lambda data: data
            return m.compress, m.decompress

        @patch(
            "scalyr_agent.util.get_compress_and_decompress_func",
            new=_mock_get_compress_and_decompress_func,
        )
        def _test(compression_type):
            self.assertIsNone(verify_and_get_compress_func(compression_type))

        _test("deflate")
        _test("bz2")
        _test("lz4")
        _test("zstandard")


class TestUtil(ScalyrTestCase):
    def setUp(self):
        super(TestUtil, self).setUp()
        self.__tempdir = tempfile.mkdtemp()
        self.__path = os.path.join(self.__tempdir, "testing.json")

    def test_read_file_as_json(self):
        self.__create_file(self.__path, '{ "a": "hi"}')

        value = scalyr_util.read_file_as_json(self.__path)
        self.assertEquals(value, {"a": "hi"})

    def test_read_config_file_as_json(self):
        self.__create_file(self.__path, '{ a: "hi"} // Test')

        json_object = scalyr_util.read_config_file_as_json(self.__path)
        self.assertEquals(json_object, JsonObject(a="hi"))

    def test_read_file_as_json_no_file(self):
        self.assertRaises(JsonReadFileException, scalyr_util.read_file_as_json, "foo")

    def test_read_file_as_json_with_bad_json(self):
        self.__create_file(self.__path, "{ a: hi}")

        self.assertRaises(
            JsonReadFileException, scalyr_util.read_file_as_json, self.__path
        )

    def test_read_file_as_json_with_strict_utf8_json(self):
        # 2->TODO python3 json libs do not allow serialization with invalid UTF-8.
        with open(self.__path, "wb") as f:
            f.write(b'{ a: "\x96"}')

        self.assertRaises(
            JsonReadFileException, scalyr_util.read_file_as_json, self.__path, True
        )

    def test_atomic_write_dict_as_json_file(self):
        info = {"a": "hi"}
        scalyr_util.atomic_write_dict_as_json_file(self.__path, self.__path + "~", info)

        json_object = scalyr_util.read_file_as_json(self.__path)
        self.assertEquals(json_object, info)

    def __create_file(self, path, contents):
        fp = open(path, "w")
        fp.write(contents)
        fp.close()

    def test_seconds_since_epoch(self):
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56)
        expected = 1438872056.0
        actual = scalyr_util.seconds_since_epoch(dt)
        self.assertEquals(expected, actual)

    def test_microseconds_since_epoch(self):
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        expected = 1438872056123456
        actual = scalyr_util.microseconds_since_epoch(dt)
        self.assertEquals(expected, actual)

    def test_uuid(self):
        first = scalyr_util.create_unique_id()
        second = scalyr_util.create_unique_id()
        self.assertTrue(len(first) > 0)
        self.assertTrue(len(second) > 0)
        self.assertNotEqual(first, second)

    def test_create_uuid3(self):
        namespace = uuid.UUID("{aaaaffff-22c7-4d50-92c1-123456781234}")
        self.assertEqual(
            scalyr_util.create_uuid3(namespace, "test-string"),
            uuid.UUID("{72a49a0a-d92e-383c-a88b-2060e372e1af}"),
        )

    def test_remove_newlines_and_truncate(self):
        self.assertEquals(scalyr_util.remove_newlines_and_truncate("hi", 1000), "hi")
        self.assertEquals(scalyr_util.remove_newlines_and_truncate("ok then", 2), "ok")
        self.assertEquals(
            scalyr_util.remove_newlines_and_truncate("o\nk\n", 1000), "o k "
        )
        self.assertEquals(
            scalyr_util.remove_newlines_and_truncate("ok\n\r there", 1000), "ok   there"
        )
        self.assertEquals(
            scalyr_util.remove_newlines_and_truncate("ok\n\r there", 6), "ok   t"
        )

    def test_is_list_of_strings_yes(self):
        self.assertTrue(scalyr_util.is_list_of_strings(["*", "blah", "dah"]))

    def test_is_list_of_strings_no(self):
        self.assertFalse(scalyr_util.is_list_of_strings(["*", 3, {"blah": "dah"}]))

    def test_is_list_of_strings_none(self):
        self.assertFalse(scalyr_util.is_list_of_strings(None))

    def test_value_to_bool(self):
        self.assertTrue(scalyr_util.value_to_bool(True))
        self.assertTrue(scalyr_util.value_to_bool(1))
        self.assertFalse(scalyr_util.value_to_bool(0))
        self.assertRaises(ValueError, scalyr_util.value_to_bool, 100)
        self.assertTrue(scalyr_util.value_to_bool("something"))
        self.assertFalse(scalyr_util.value_to_bool("f"))
        self.assertFalse(scalyr_util.value_to_bool("False"))
        self.assertFalse(scalyr_util.value_to_bool(""))

    def test_get_parser_from_config_default(self):
        config = {
            "something": "something",
            "other something": ["thing1", "thing2"],
        }
        attributes = {"nothing": 0}

        self.assertEqual(
            scalyr_util.get_parser_from_config(config, attributes, "default_parser"),
            "default_parser",
        )

    def test_get_parser_from_config_hierarchy1(self):
        config = {
            "something": "something",
            "other something": ["thing1", "thing2"],
            "parser": "config_parser",
            "attributes": {"parser": "config_attributes_parser"},
        }
        attributes = {
            "nothing": 0,
            "parser": "attributes_parser",
        }

        self.assertEqual(
            scalyr_util.get_parser_from_config(config, attributes, "default_parser"),
            "config_attributes_parser",
        )

    def test_get_parser_from_config_hierarchy2(self):
        config = {
            "something": "something",
            "other something": ["thing1", "thing2"],
            "parser": "config_parser",
            "attributes": {},
        }
        attributes = {
            "nothing": 0,
            "parser": "attributes_parser",
        }

        self.assertEqual(
            scalyr_util.get_parser_from_config(config, attributes, "default_parser"),
            "config_parser",
        )

    def test_get_parser_from_config_hierarchy3(self):
        config = {
            "something": "something",
            "other something": ["thing1", "thing2"],
            "attributes": {},
        }
        attributes = {
            "nothing": 0,
            "parser": "attributes_parser",
        }

        self.assertEqual(
            scalyr_util.get_parser_from_config(config, attributes, "default_parser"),
            "attributes_parser",
        )

    def test_get_web_url_from_upload_url(self):
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://agent.scalyr.com"),
            "https://www.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://log.scalyr.com"),
            "https://www.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://upload.scalyr.com"),
            "https://www.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://app.scalyr.com"),
            "https://www.scalyr.com",
        )

        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://agent.eu.scalyr.com"),
            "https://www.eu.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://log.eu.scalyr.com"),
            "https://www.eu.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://upload.eu.scalyr.com"),
            "https://www.eu.scalyr.com",
        )
        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://app.eu.scalyr.com"),
            "https://www.eu.scalyr.com",
        )

        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://logstaging.scalyr.com"),
            "https://logstaging.scalyr.com",
        )

        self.assertEqual(
            scalyr_util.get_web_url_from_upload_url("https://logstaging.eu.scalyr.com"),
            "https://logstaging.eu.scalyr.com",
        )


class TestUtilWithLogCapture(BaseScalyrLogCaptureTestCase):
    def setUp(self):
        super(TestUtilWithLogCapture, self).setUp()
        self.__logger = scalyr_logging.getLogger("util")
        self.__logger.set_keep_last_record(False)
        self.__tempdir = tempfile.mkdtemp()
        self.__path = os.path.join(self.__tempdir, "testing.json")
        self.__temp_file_path = self.__path + "~"

    def test_atomic_write_dict_as_json_file_error(self):
        # mock of the 'atomic_write_dict_as_json_file' internal funtion calls to raise an error
        # and validate the error log message.
        info = {"a": "hi"}
        with patch("os.rename") as os_rename_mock:
            os_rename_mock.side_effect = Exception("I am an error.")
            scalyr_util.atomic_write_dict_as_json_file(
                self.__path, self.__temp_file_path, info
            )

        self.assertLogFileContainsLineRegex(expression="I am an error.")
        self.assertLogFileContainsLineRegex(
            expression="File path: '{0}', type: {1}".format(
                re.escape(self.__path), type(self.__path)
            )
        )
        self.assertLogFileContainsLineRegex(
            expression="Temporary file path: '{0}', type: {1}".format(
                re.escape(self.__temp_file_path), type(self.__temp_file_path)
            )
        )
        self.assertLogFileContainsLineRegex(expression="File exists: False.")
        self.assertLogFileContainsLineRegex(expression="Temporary file exists: True.")
        self.assertLogFileContainsLineRegex(
            expression="File system encoding: {0}".format(
                re.escape(sys.getfilesystemencoding())
            )
        )


class TestRateLimiter(ScalyrTestCase):
    def setUp(self):
        super(TestRateLimiter, self).setUp()
        self.__test_rate = RateLimiter(100, 10, current_time=0)
        self.__current_time = 0
        self.__last_sleep_amount = -1

    def advance_time(self, delta):
        self.__current_time += delta

    def charge_if_available(self, num_bytes):
        return self.__test_rate.charge_if_available(
            num_bytes, current_time=self.__current_time
        )

    def block_until_charge_succeeds(self, num_bytes):
        return self.__test_rate.block_until_charge_succeeds(
            num_bytes, current_time=self.__current_time
        )

    def test_basic_use(self):
        self.assertTrue(self.charge_if_available(20))
        self.assertTrue(self.charge_if_available(80))
        self.assertFalse(self.charge_if_available(1))

    def test_custom_bucket_size_and_rate(self):
        self.__test_rate = RateLimiter(10, 1, current_time=0)
        self.assertTrue(self.charge_if_available(10))
        self.assertFalse(self.charge_if_available(10))
        self.advance_time(1)
        self.assertFalse(self.charge_if_available(10))
        self.advance_time(5)
        self.assertFalse(self.charge_if_available(10))

    def test_zero_bucket_fill_rate(self):
        self.__test_rate = RateLimiter(100, 0, current_time=0)
        self.assertTrue(self.charge_if_available(20))
        self.assertTrue(self.charge_if_available(80))
        self.assertFalse(self.charge_if_available(1))
        self.advance_time(1)
        self.assertFalse(self.charge_if_available(20))
        self.advance_time(5)
        self.assertFalse(self.charge_if_available(20))

    def test_refill(self):
        self.assertTrue(self.charge_if_available(60))
        self.assertFalse(self.charge_if_available(60))
        self.advance_time(1)
        self.assertFalse(self.charge_if_available(60))
        self.advance_time(1)
        self.assertTrue(self.charge_if_available(60))

    def fake_sleep(self, seconds):
        self.__last_sleep_amount = seconds
        self.advance_time(seconds)

    def test_basic_use_sleep(self):
        with mock.patch("scalyr_agent.util.time.sleep", self.fake_sleep):
            self.__last_sleep_amount = -1
            self.block_until_charge_succeeds(20)
            self.assertEqual(self.__last_sleep_amount, -1)
            self.block_until_charge_succeeds(80)
            self.assertEqual(self.__last_sleep_amount, -1)
            self.block_until_charge_succeeds(1)
            self.assertEqual(self.__last_sleep_amount, 0.1)

    def test_custom_bucket_size_and_rate_sleep(self):
        with mock.patch("scalyr_agent.util.time.sleep", self.fake_sleep):
            self.__last_sleep_amount = -1
            self.__test_rate = RateLimiter(10, 1, current_time=0)
            self.block_until_charge_succeeds(10)
            self.assertEqual(self.__last_sleep_amount, -1)
            self.block_until_charge_succeeds(10)
            self.assertEqual(self.__last_sleep_amount, 10)
            self.advance_time(15)
            self.block_until_charge_succeeds(20)
            self.assertEqual(self.__last_sleep_amount, 10)

    def test_zero_bucket_fill_rate_sleep(self):
        self.__test_rate = RateLimiter(100, 0, current_time=0)
        self.assertRaises(ValueError, self.block_until_charge_succeeds, 20)

    def test_refill_sleep(self):
        with mock.patch("scalyr_agent.util.time.sleep", self.fake_sleep):
            self.__last_sleep_amount = -1
            self.block_until_charge_succeeds(60)
            self.assertEqual(self.__last_sleep_amount, -1)
            self.block_until_charge_succeeds(60)
            self.assertEqual(self.__last_sleep_amount, 2)
            self.advance_time(1)
            self.block_until_charge_succeeds(60)
            self.assertEqual(self.__last_sleep_amount, 5)

    def test_charge_greater_than_bucket_size_sleep(self):
        with mock.patch("scalyr_agent.util.time.sleep", self.fake_sleep):
            self.__last_sleep_amount = -1
            self.__test_rate = RateLimiter(10, 1, current_time=0)
            self.block_until_charge_succeeds(20)
            self.assertEqual(self.__last_sleep_amount, 10)


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
        super(TestStoppableThread, self).setUp()
        self._run_counter = 0

    def test_basic_use(self):
        # Since the ScalyrTestCase sets the name prefix, we need to set it back to None to get an unmolested name.
        StoppableThread.set_name_prefix(None)
        test_thread = StoppableThread("Testing", self._run_method)
        self.assertEqual(test_thread.getName(), "Testing")
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_name_prefix(self):
        StoppableThread.set_name_prefix("test_name_prefix: ")
        test_thread = StoppableThread("Testing", self._run_method)
        self.assertEqual(test_thread.getName(), "test_name_prefix: Testing")
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_name_prefix_with_none(self):
        StoppableThread.set_name_prefix("test_name_prefix: ")
        test_thread = StoppableThread(target=self._run_method)
        self.assertEqual(test_thread.getName(), "test_name_prefix: ")
        test_thread.start()
        test_thread.stop()

        self.assertTrue(self._run_counter > 0)

    def test_basic_extending(self):
        class TestThread(StoppableThread):
            def __init__(self):
                self.run_counter = 0
                StoppableThread.__init__(self, "Test thread")

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

        test_thread = StoppableThread("Testing", throw_an_exception)
        test_thread.start()

        caught_it = False
        try:
            test_thread.stop()
        except TestException:
            caught_it = True

        self.assertTrue(caught_it)

    def test_is_alive(self):
        class TestThread(StoppableThread):
            def __init__(self):
                self.run_counter = 0
                StoppableThread.__init__(self, "Test thread")

            def run_and_propagate(self):
                while self._run_state.is_running():
                    self._run_state.sleep_but_awaken_if_stopped(0.03)

        test_thread_1 = TestThread()
        test_thread_2 = StoppableThread("Testing", self._run_method)

        test_threads = [test_thread_1, test_thread_2]

        for test_thread in test_threads:
            self.assertFalse(test_thread.isAlive())

            if six.PY3:
                self.assertFalse(test_thread.is_alive())

            test_thread.start()

            self.assertTrue(test_thread.isAlive())

            if six.PY3:
                self.assertTrue(test_thread.is_alive())

            test_thread.stop()
            self.assertFalse(test_thread.isAlive())

            if six.PY3:
                self.assertFalse(test_thread.is_alive())

    def _run_method(self, run_state):
        self._run_counter += 1
        while run_state.is_running():
            self._run_counter += 1
            run_state.sleep_but_awaken_if_stopped(0.03)

    def test_register_on_stop_callback(self):
        self.callback_called = False

        def fake_callback():
            self.callback_called = True

        run_state = scalyr_util.RunState()
        run_state.register_on_stop_callback(fake_callback)
        run_state.stop()
        self.assertTrue(self.callback_called)

    def test_remove_on_stop_callback(self):
        self.callback_called = False

        def fake_callback():
            self.callback_called = True

        run_state = scalyr_util.RunState()
        run_state.register_on_stop_callback(fake_callback)
        run_state.remove_on_stop_callback(fake_callback)
        run_state.stop()
        self.assertFalse(self.callback_called)


class TestScriptEscalator(ScalyrTestCase):
    def tearDown(self):
        super(TestScriptEscalator, self).tearDown()

        if "__main__" in sys.modules:
            del sys.modules["__main__"]

    def test_is_user_change_required(self):
        (test_instance, controller) = self.create_instance("czerwin", "fileA", "steve")
        self.assertTrue(test_instance.is_user_change_required())

        (test_instance, controller) = self.create_instance(
            "czerwin", "fileA", "czerwin"
        )
        self.assertFalse(test_instance.is_user_change_required())

    def test_change_user_and_rerun_script(self):
        # NOTE: __main__.__file__ might not be set when running tests under pytests or nosetests
        mock_main = mock.Mock()
        mock_main.__file__ = "/tmp/file.py"
        sys.modules["__main__"] = mock_main

        (test_instance, controller) = self.create_instance("czerwin", "fileA", "steve")
        self.assertEquals(test_instance.change_user_and_rerun_script("random"), 0)

        self.assertEquals(controller.call_count, 1)
        self.assertEquals(controller.last_call["user"], "steve")
        self.assertEqual(controller.last_call["script_file"], "/tmp/file.py")

    def create_instance(self, current_user, config_file, config_owner):
        controller = TestScriptEscalator.ControllerMock(
            current_user, config_file, config_owner
        )
        # noinspection PyTypeChecker
        return ScriptEscalator(controller, config_file, os.getcwd()), controller

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
                "user": user,
                "script_file": script_file_path,
                "script_binary": script_binary,
                "script_args": script_args,
            }
            return 0


class TestRedirectorServer(ScalyrTestCase):
    """Tests the RedirectorServer code using fakes for stdout, stderr and the channel."""

    def setUp(self):
        super(TestRedirectorServer, self).setUp()
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
        self._sys.stdout.write("Testing")
        # Make sure we wrote a message to the channel
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 0)
        self.assertEquals(content, "Testing")

    def test_sending_unicode(self):
        self._server.start()
        self.assertEquals(self._channel.accept_count, 1)
        self._sys.stdout.write("caf\xe9")
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 0)
        self.assertEquals(content, "caf\xe9")

    def test_sending_to_stderr(self):
        self._server.start()
        self.assertEquals(self._channel.accept_count, 1)
        self._sys.stderr.write("Testing again")
        self.assertEquals(self._channel.write_count, 1)
        (stream_id, content) = self._parse_sent_bytes(self._channel.last_write)

        self.assertEquals(stream_id, 1)
        self.assertEquals(content, "Testing again")

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
        @type content: six.binary_type

        @return: A tuple of the stream_id and the actual content encoded in the sent string.
        @rtype: (int,six.text_type)
        """
        prefix_code = content[0:4]
        # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
        code = compat.struct_unpack_unicode("i", prefix_code)[0]
        stream_id = code % 2
        num_bytes = code >> 1

        self.assertEquals(len(content), num_bytes + 4)
        decoded_str = content[4:].decode("utf-8")

        return stream_id, decoded_str


class TestRedirectorClient(ScalyrTestCase):
    """Test the RedirectorClient by faking out the client channel and also the clock."""

    def setUp(self):
        super(TestRedirectorClient, self).setUp()
        self._fake_sys = FakeSys()
        # Since the client is an actual other thread that blocks waiting for input from the server, we have to
        # simulate the time using a fake clock.  That will allow us to wait up the client thread from time to time.
        self._fake_clock = scalyr_util.FakeClock()
        # The fake channel allows us to insert bytes being sent by the server.
        self._client_channel = FakeClientChannel(self._fake_clock)
        self._client = RedirectorClient(
            self._client_channel, sys_impl=self._fake_sys, fake_clock=self._fake_clock
        )
        self._client.start()
        # Wait until the client thread begins to block for the initial accept from the server.
        self._fake_clock.block_until_n_waiting_threads(1)

    def tearDown(self):
        if self._client is not None:
            self._client.stop(wait_on_join=False)
            self._fake_clock.advance_time(set_to=59.0)
            self._client.join()

    def test_receiving_bytes(self):
        # Simulate accepting the connection.
        self._accept_client_connection()
        self._send_to_client(0, "Testing")
        # Wait until have bytes written to stdout by the client thread.
        self._fake_sys.stdout.wait_for_bytes(1.0)
        self.assertEquals(self._fake_sys.stdout.last_write, "Testing")

    def test_receiving_unicode(self):
        self._accept_client_connection()
        self._send_to_client(0, "caf\xe9")
        self._fake_sys.stdout.wait_for_bytes(1.0)
        self.assertEquals(self._fake_sys.stdout.last_write, "caf\xe9")

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
        self._send_to_client(-1, "")
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
        if type(content) is six.text_type:
            encoded_content = six.text_type(content).encode("utf-8")
        else:
            encoded_content = content
        code = len(encoded_content) * 2 + stream_id
        # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
        self._client_channel.simulate_server_write(
            compat.struct_pack_unicode("i", code) + encoded_content
        )


class TestRedirectionService(ScalyrTestCase):
    """Tests both the RedirectorServer and the RedirectorClient communicating together."""

    def setUp(self):
        super(TestRedirectionService, self).setUp()
        self._client_sys = FakeSys()
        self._server_sys = FakeSys()
        self._fake_clock = scalyr_util.FakeClock()
        self._client_channel = FakeClientChannel(self._fake_clock)
        self._server_channel = FakeServerChannel(self._client_channel)
        self._client = RedirectorClient(
            self._client_channel, sys_impl=self._client_sys, fake_clock=self._fake_clock
        )
        self._server = RedirectorServer(self._server_channel, sys_impl=self._server_sys)
        self._client.start()
        self._server.start()

    def test_end_to_end(self):
        self._server_sys.stdout.write("Test full")
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
        self._pending_content = b""
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
        self._pending_content = b"%s%s" % (self._pending_content, content)
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
            try:
                if self._last_write is not None:
                    return
                self._condition.wait(timeout)
            finally:
                self._condition.release()


class TestHistogramTracker(ScalyrTestCase):
    """Tests the HistogramTracker abstraction."""

    def setUp(self):
        super(TestHistogramTracker, self).setUp()
        self._testing = HistogramTracker([10, 25, 50, 100])

    def test_count(self):
        self.assertEqual(self._testing.count(), 0)

        self._testing.add_sample(1)
        self._testing.add_sample(11)
        self.assertEqual(self._testing.count(), 2)

        self._testing.reset()
        self.assertEqual(self._testing.count(), 0)

    def test_average(self):
        self._testing.add_sample(1)
        self._testing.add_sample(11)
        self.assertAlmostEqual(self._testing.average(), 6.0)

        self._testing.reset()
        self.assertIsNone(self._testing.average())

        self._testing.add_sample(6)
        self.assertAlmostEqual(self._testing.average(), 6.0)

    def test_min(self):
        self._testing.add_sample(1)
        self._testing.add_sample(11)
        self.assertAlmostEqual(self._testing.min(), 1.0)

        self._testing.add_sample(15)
        self.assertAlmostEqual(self._testing.min(), 1.0)

        self._testing.add_sample(0.5)
        self.assertAlmostEqual(self._testing.min(), 0.5)

        self._testing.reset()
        self.assertIsNone(self._testing.min())

        self._testing.add_sample(15)
        self.assertAlmostEqual(self._testing.min(), 15.0)

    def test_max(self):
        self._testing.add_sample(1)
        self._testing.add_sample(11)
        self.assertAlmostEqual(self._testing.max(), 11.0)

        self._testing.add_sample(15)
        self.assertAlmostEqual(self._testing.max(), 15.0)

        self._testing.add_sample(0.5)
        self.assertAlmostEqual(self._testing.max(), 15.0)

        self._testing.reset()
        self.assertIsNone(self._testing.max())

        self._testing.add_sample(0)
        self.assertAlmostEqual(self._testing.max(), 0)

    def test_buckets(self):
        buckets = self._buckets_to_list()
        self.assertEqual(len(buckets), 0)

        self._testing.add_sample(2)
        buckets = self._buckets_to_list()
        self.assertEqual(len(buckets), 1)
        self.assertBucketEquals(buckets[0], (1, 2, 10))

        self._testing.add_sample(50)
        buckets = self._buckets_to_list()
        self.assertEqual(len(buckets), 2)
        self.assertBucketEquals(buckets[0], (1, 2, 10))
        self.assertBucketEquals(buckets[1], (1, 50, 100))

        self._testing.add_sample(5)
        buckets = self._buckets_to_list()
        self.assertEqual(len(buckets), 2)
        self.assertBucketEquals(buckets[0], (2, 2, 10))
        self.assertBucketEquals(buckets[1], (1, 50, 100))

        self._testing.add_sample(200)
        buckets = self._buckets_to_list()
        self.assertEqual(len(buckets), 3)
        self.assertBucketEquals(buckets[0], (2, 2, 10))
        self.assertBucketEquals(buckets[1], (1, 50, 100))
        self.assertBucketEquals(buckets[2], (1, 100, 200.01))

    def test_estimate_percentile(self):
        self.assertIsNone(self._testing.estimate_median())

        self._testing.add_sample(0)
        self._testing.add_sample(3)
        self._testing.add_sample(4)
        # Since all of the values fall into the first bucket, the estimate of the percentile will be the same for all
        # percentiles.
        self.assertAlmostEqual(self._testing.estimate_percentile(0.1), 5.0)
        self.assertAlmostEqual(self._testing.estimate_percentile(0.5), 5.0)
        self.assertAlmostEqual(self._testing.estimate_percentile(1.0), 5.0)

        self._testing.add_sample(11)
        self._testing.add_sample(12)
        self._testing.add_sample(13)
        self._testing.add_sample(55)

        self.assertAlmostEqual(self._testing.estimate_percentile(0.1), 5.0)
        self.assertAlmostEqual(self._testing.estimate_percentile(0.5), 17.5)
        self.assertAlmostEqual(self._testing.estimate_percentile(1.0), 75.0)

    def test_summarize(self):
        self.assertEqual(self._testing.summarize(), "(count=0)")

        self._testing.add_sample(2)
        self._testing.add_sample(4)
        self._testing.add_sample(45)
        self._testing.add_sample(200)

        self.assertEqual(
            self._testing.summarize(),
            "(count=4,avg=62.75,min=2.00,max=200.00,median=6.00)",
        )

    def assertBucketEquals(self, first, second):
        self.assertEquals(first[0], second[0], msg="The counts do not equal")
        self.assertAlmostEquals(
            first[1], second[1], msg="The lower bounds do not equal"
        )
        self.assertAlmostEquals(
            first[2], second[2], msg="The upper bounds do not equal"
        )

    def _buckets_to_list(self):
        result = []
        for count, lower, upper in self._testing.buckets():
            result.append((count, lower, upper))
        return result


class TestParseValueWithRate(ScalyrTestCase):
    def test_numerators(self):
        self.assertEqual(100, scalyr_util.parse_data_rate_string("100 B/s"))
        self.assertEqual(100 * 1000, scalyr_util.parse_data_rate_string("100 kB/s"))
        self.assertEqual(
            100 * 1000 * 1000, scalyr_util.parse_data_rate_string("100 mB/s")
        )
        self.assertEqual(
            100 * 1000 * 1000 * 1000, scalyr_util.parse_data_rate_string("100 gB/s")
        )
        self.assertEqual(
            100 * 1000 * 1000 * 1000 * 1000,
            scalyr_util.parse_data_rate_string("100 tB/s"),
        )
        self.assertEqual(100 * 1024, scalyr_util.parse_data_rate_string("100 kiB/s"))
        self.assertEqual(
            100 * 1024 * 1024, scalyr_util.parse_data_rate_string("100 miB/s")
        )
        self.assertEqual(
            100 * 1024 * 1024 * 1024, scalyr_util.parse_data_rate_string("100 giB/s")
        )
        self.assertEqual(
            100 * 1024 * 1024 * 1024 * 1024,
            scalyr_util.parse_data_rate_string("100 tiB/s"),
        )

    def test_denominators(self):
        self.assertEqual(100000, scalyr_util.parse_data_rate_string("100000 B/s"))
        self.assertEqual(
            100000 / 60.0, scalyr_util.parse_data_rate_string("100000 B/m")
        )
        self.assertEqual(
            100000 / 60.0 / 60.0, scalyr_util.parse_data_rate_string("100000 B/h")
        )
        self.assertEqual(
            100000 / 60.0 / 60.0 / 24.0,
            scalyr_util.parse_data_rate_string("100000 B/d"),
        )
        self.assertEqual(
            100000 / 60.0 / 60.0 / 24.0 / 7.0,
            scalyr_util.parse_data_rate_string("100000 B/w"),
        )

    def test_spacing(self):
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1kiB/s"))
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1 kiB/s"))
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1\tkiB/s"))
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1   \t   \t  kiB/s"))

    def test_capitalization(self):
        self.assertEqual(100, scalyr_util.parse_data_rate_string("100 B/S"))
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 b/S")
        self.assertEqual(100, scalyr_util.parse_data_rate_string("100 B/s"))
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 b/s")

        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1KiB/S"))
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1kIB/S"))
        self.assertEqual(1000, scalyr_util.parse_data_rate_string("1KB/S"))
        self.assertEqual(1000, scalyr_util.parse_data_rate_string("1kB/S"))
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "1Kb/S")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "1kib/S")
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1KiB/s"))
        self.assertEqual(1024, scalyr_util.parse_data_rate_string("1kIB/s"))
        self.assertEqual(1000, scalyr_util.parse_data_rate_string("1KB/s"))
        self.assertEqual(1000, scalyr_util.parse_data_rate_string("1kB/s"))
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "1Kb/s")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "1kb/s")

    def test_values(self):
        self.assertEqual(100, scalyr_util.parse_data_rate_string("100 B/s"))
        self.assertEqual(-100, scalyr_util.parse_data_rate_string("-100 B/s"))
        self.assertEqual(0, scalyr_util.parse_data_rate_string("0 B/s"))
        self.assertEqual(0, scalyr_util.parse_data_rate_string("0 gB/s"))
        self.assertEqual(0, scalyr_util.parse_data_rate_string("-0 gB/s"))
        self.assertEqual(-100.2456, scalyr_util.parse_data_rate_string("-100.2456 B/s"))
        self.assertEqual(
            199.000001, scalyr_util.parse_data_rate_string("199.000001 B/s")
        )

        self.assertEqual(
            1024 * 1024 * 1024 * 1024 / 60.0 / 60.0 / 24.0 / 7.0,
            scalyr_util.parse_data_rate_string("1 tiB/w"),
        )

    def test_invalid_inputs(self):
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "B/s")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 /")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "- B/s")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 YB/s")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 B/C")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 D/s")
        self.assertRaises(ValueError, scalyr_util.parse_data_rate_string, "100 g1/s")
