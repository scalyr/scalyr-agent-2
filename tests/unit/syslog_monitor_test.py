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
# author: Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import


if False:
    from typing import List

__author__ = "imron@scalyr.com"

import time
import sys
import socket
import unittest
import logging
import uuid
import os
from io import open
from io import StringIO
import threading
import platform

from scalyr_agent.builtin_monitors import syslog_monitor
from scalyr_agent.builtin_monitors.syslog_monitor import SyslogMonitor
from scalyr_agent.builtin_monitors.syslog_monitor import SyslogFrameParser
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.scalyr_monitor import MonitorInformation
from scalyr_agent.test_base import ScalyrTestCase
import scalyr_agent.scalyr_logging as scalyr_logging

import six
import mock

from scalyr_agent.test_base import skipIf


class SyslogFrameParserTestCase(unittest.TestCase):
    def test_framed_messages(self):
        parser = SyslogFrameParser(32)
        message = StringIO()
        message.write("5 hello5 world")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual("hello", actual)

        actual = parser.parse_request(message, 32)
        self.assertEqual("world", actual)

        actual = parser.parse_request(message, 32)
        self.assertEqual(None, actual)

    def test_framed_message_incomplete(self):
        parser = SyslogFrameParser(32)
        message = StringIO()
        message.write("11 hello")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual(None, actual)

        message.seek(8)
        message.write(" world")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual("hello world", actual)

    def test_framed_message_invalid_frame_size(self):
        parser = SyslogFrameParser(32)
        message = StringIO()
        message.write("1a1 hello")
        message.seek(0)

        self.assertRaises(ValueError, lambda: parser.parse_request(message, 32))

    def test_framed_message_exceeds_max_size(self):
        parser = SyslogFrameParser(10)
        message = StringIO()
        message.write("11 hello world")
        message.seek(0)

        self.assertRaises(
            RequestSizeExceeded, lambda: parser.parse_request(message, 32)
        )

    def test_unframed_messages(self):
        parser = SyslogFrameParser(32)
        message = StringIO()
        message.write("hello\nworld\n")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual("hello\n", actual)

        actual = parser.parse_request(message, 32)
        self.assertEqual("world\n", actual)

        actual = parser.parse_request(message, 32)
        self.assertEqual(None, actual)

    def test_unframed_messages_incomplete(self):
        parser = SyslogFrameParser(32)
        message = StringIO()
        message.write("hello")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual(None, actual)

        message.seek(5)
        message.write(" world\n")
        message.seek(0)

        actual = parser.parse_request(message, 32)
        self.assertEqual("hello world\n", actual)

    def test_unframed_message_exceeds_max_size(self):
        parser = SyslogFrameParser(10)
        message = StringIO()
        message.write("hello world\n")
        message.seek(0)

        self.assertRaises(
            RequestSizeExceeded, lambda: parser.parse_request(message, 32)
        )


class SyslogMonitorTestCase(ScalyrTestCase):
    def assertNoException(self, func):
        try:
            func()
        except Exception as e:
            self.fail("Unexpected Exception: %s" % six.text_type(e))
        except Exception:
            self.fail("Unexpected Exception: %s" % sys.exc_info()[0])


class SyslogMonitorConfigTest(SyslogMonitorTestCase):
    def test_config_protocol_udp(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "udp",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_udp_upper(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "UDP",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_tcp(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_tcp_upper(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "TCP",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_multiple(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp, udp",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_multiple_with_ports(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:4096, udp:5082",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_multiple_two(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp, udp",
        }
        self.assertNoException(
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            )
        )

    def test_config_protocol_invalid(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "XXX",
        }
        self.assertRaises(
            Exception,
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            ),
        )

    def test_config_protocol_empty(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "",
        }
        self.assertRaises(
            Exception,
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            ),
        )

    def test_config_port_too_high(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "udp:70000",
        }
        self.assertRaises(
            Exception,
            lambda: SyslogMonitor(
                config, scalyr_logging.getLogger("syslog_monitor[test]")
            ),
        )


class TestSyslogMonitor(SyslogMonitor):
    """subclass of SyslogMonitor with overridden 'increment_counter'.
        Provides ability to suspend test thread until written lines are handled by 'increment_counter' method.
        """

    __test__ = False

    def __init__(self, *args, **kwargs):
        super(TestSyslogMonitor, self).__init__(*args, **kwargs)
        # wakes up the main test thread when new line added, and line counter incremented.
        self._increment_line_cv = threading.Condition()

        # stores the total number of 'reported_lines'. Useful when multiple lines are sent at once.
        self._reported_lines_count = 0

        # stores number of calls of the increment_counter / line_reporter function
        self._increment_counter_call_count = 0

    def increment_counter(self, reported_lines=0, errors=0):
        super(TestSyslogMonitor, self).increment_counter(
            reported_lines=reported_lines, errors=errors
        )

        self._increment_counter_call_count += 1

        with self._increment_line_cv:
            self._reported_lines_count += reported_lines
            self._increment_line_cv.notify()

    def wait_for_new_lines(self, expected_line_number=1, timeout=3):
        """
        Wait until written lines are processed by 'increment_counter' method.
        :param expected_line_number: number of expected lines.
        :param timeout: time in seconds to wait, before timeout exception.
        """
        with self._increment_line_cv:
            start_time = time.time()
            while self._reported_lines_count != expected_line_number:
                self._increment_line_cv.wait(timeout)
                if time.time() - start_time >= timeout:
                    raise OSError(
                        "Could not wait for written lines because the timeout (%s seconds) has occurred."
                        % (timeout)
                    )
            self._reported_lines_count = 0


class TestSyslogHandler(syslog_monitor.SyslogHandler):
    """Subclass of the SyslogHandler. It does not affect any internal logic, it just only make some check assertions."""

    def handle(self, data):
        assert (
            type(data) == six.text_type
        ), "SyslogHandler.handle function accepts only unicode strings."
        return super(TestSyslogHandler, self).handle(data)


class SyslogMonitorConnectTest(SyslogMonitorTestCase):
    @classmethod
    def setUpClass(cls):
        # clear the syslog disk logger
        try:
            os.remove("agent_syslog.log")
        except OSError:
            pass

    def setUp(self):
        super(SyslogMonitorConnectTest, self).setUp()
        self.monitor = None
        self.sockets = []

        # capture log output
        scalyr_logging.set_log_destination(use_stdout=True)
        scalyr_logging.set_log_level(scalyr_logging.DEBUG_LEVEL_0)
        self.logger = logging.getLogger(
            "scalyr_agent.builtin_monitors.syslog_monitor.syslog"
        )
        self.logger.setLevel(logging.INFO)
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.logger.addHandler(self.handler)

        # Allow tcp_buffer_size to be set to less than 2k
        for option in MonitorInformation.__monitor_info__[
            "scalyr_agent.builtin_monitors.syslog_monitor"
        ].config_options:
            if option.option_name == "tcp_buffer_size":
                option.min_value = 0

        # hide stdout
        self.old = sys.stdout

        # Replace sys.stdout with 'dummy' StringIO.
        # We must have one more variable which points to our 'dummy' stream because
        # Pytest can replace 'sys.stdout' with its own stream,
        # so we will not be able to access 'dummy' stream after that.
        self.dummy_stream = StringIO()
        sys.stdout = self.dummy_stream

    def tearDown(self):
        # It's important we close all the open FDs used by loggers otherwise tests will fail on
        # Windows because the file will still be opened
        scalyr_logging.close_handlers()

        # close any open sockets
        for s in self.sockets:
            s.close()

        # stop any running monitors - this might be open if an exception was thrown before a test called monitor.stop()
        if self.monitor is not None:
            self.monitor.stop(wait_on_join=False)

        self.logger.removeHandler(self.handler)
        self.handler.close()

        # restore stdout
        sys.stdout = self.old

        # Print any accumulated stdout at the end for ease of debugging
        self.dummy_stream.close()

    def connect(self, socket, addr, max_tries=3):
        connected = False
        tries = 0
        while not connected and tries < max_tries:
            try:
                socket.connect(addr)
                connected = True
            except Exception:
                time.sleep(0.1)
            tries += 1

        return connected

    def send_and_wait_for_lines(
        self,
        sock,
        data,
        dest_addr=None,
        expected_line_count=1,
        timeout=3,
        wait_for_lines=True,
    ):
        """
        Send data through a 'sock' socket.
        :param dest_addr: if not None, sends 'data' via UDP.
        :param expected_line_count: number of expected lines.
        :type dest_addr: tuple
        :type data: six.text_type or list of six.text_type
        """
        data_to_send = []  # type: List[bytes]

        if not isinstance(data, list):
            data_to_send = [data]
        else:
            data_to_send = data

        if dest_addr is None:
            for chunk in data_to_send:
                if not isinstance(chunk, six.binary_type):
                    chunk = chunk.encode("utf-8")
                sock.sendall(chunk)
        else:
            for chunk in data_to_send:
                if not isinstance(chunk, six.binary_type):
                    chunk = chunk.encode("utf-8")
                sock.sendto(chunk, dest_addr)

        if wait_for_lines:
            self.monitor.wait_for_new_lines(
                expected_line_number=expected_line_count, timeout=timeout
            )

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    def test_run_tcp_server_handle_frame_timeout(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_buffer_size": 500,
        }

        # 1. non-framed message, we use \n as frame end maker
        self.monitor = TestSyslogMonitor(config, self.logger)
        self.monitor.open_metric_log()

        self.monitor.start()
        time.sleep(0.05)

        s = socket.socket(socket.AF_INET)
        self.sockets.append(s)

        self.connect(s, ("localhost", 8514))

        # Single line which is sent as part of a single TCP send call which exceeds the buffer size
        self.monitor._reported_lines_count = 0
        expected_line1 = "TCP line one without line break"

        expected_msg = r"Could not wait for written lines because the timeout \(2 seconds\) has occurred"

        self.assertRaisesRegexp(
            OSError,
            expected_msg,
            self.send_and_wait_for_lines,
            s,
            expected_line1,
            expected_line_count=1,
            timeout=2,
        )

        self.assertEqual(self.monitor._increment_counter_call_count, 0)

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    @mock.patch("scalyr_agent.builtin_monitors.syslog_monitor.global_log")
    def test_run_tcp_server_small_tcp_buffer_size_without_unlimited_buffer_size(
        self, mock_global_log
    ):
        # unlimited buffer size is False and tcp_buffer_size is False. Timeout should occur because
        # partial data should be flushed before we receive a whole line
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_buffer_size": 5,
            "tcp_unlimited_buffer_size": False,
        }

        self.monitor = TestSyslogMonitor(config, self.logger)
        self.monitor.open_metric_log()

        self.monitor.start()
        time.sleep(0.05)

        s = socket.socket(socket.AF_INET)
        self.sockets.append(s)

        self.connect(s, ("localhost", 8514))

        expected_line1 = "TCP line one without line break"

        self.assertEqual(mock_global_log.warning.call_count, 0)

        self.send_and_wait_for_lines(
            s, expected_line1, expected_line_count=0, wait_for_lines=False
        )
        time.sleep(2)

        # Ensure we did actually call handle_frame for each of the small frames
        self.assertEqual(
            int(len(expected_line1) / 5), self.monitor._increment_counter_call_count
        )

        self.assertEqual(mock_global_log.warning.call_count, 6)
        self.assertTrue(
            "frame exceeded maximum buffer size of 5 bytes"
            in mock_global_log.warning.call_args_list[0][0][0]
        )
        self.assertTrue(
            "frame exceeded maximum buffer size of 5 bytes"
            in mock_global_log.warning.call_args_list[5][0][0]
        )

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    @mock.patch("scalyr_agent.builtin_monitors.syslog_monitor.global_log")
    def test_run_tcp_server_small_tcp_buffer_size_with_unlimited_buffer_size(
        self, mock_global_log
    ):
        # When tcp_unlimited_buffer_size config option is set to True, we should support messages
        # which span multiple packets and are more than tcp_buffer_size in size
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_buffer_size": 5,
            "tcp_unlimited_buffer_size": True,
        }

        self.monitor = TestSyslogMonitor(config, self.logger)
        self.monitor.open_metric_log()

        self.monitor.start()
        time.sleep(0.05)

        s = socket.socket(socket.AF_INET)
        self.sockets.append(s)

        self.connect(s, ("localhost", 8514))

        # Single line which is sent as part of a single TCP send call which exceeds the buffer size
        self.monitor._reported_lines_count = 0

        self.assertEqual(mock_global_log.warning.call_count, 0)

        expected_line1 = "TCP TestXX Foo bar baz"
        self.send_and_wait_for_lines(s, expected_line1 + "\n", expected_line_count=1)

        self.assertEqual(mock_global_log.warning.call_count, 0)

        # Single line which is split across multiple TCP packets
        expected_line2_partial_1 = "Hello "
        expected_line2_partial_2 = "Howdy "
        expected_line2_partial_3 = "stranger bar foo bar ponies"
        expected_line2 = (
            expected_line2_partial_1
            + expected_line2_partial_2
            + expected_line2_partial_3
        )
        self.send_and_wait_for_lines(
            s,
            [
                expected_line2_partial_1,
                expected_line2_partial_2,
                expected_line2_partial_3 + "\n",
            ],
            expected_line_count=1,
        )

        # Multiple lines which exceed tcp buffer size
        # NOTE: It's important we reset _reported_lines_count between each test scenario
        self.monitor._reported_lines_count = 0

        expected_line3 = "hello this is line one\nbut also line two\nand maybe also line three\nand so on and so on"
        self.send_and_wait_for_lines(s, expected_line3 + "\n", expected_line_count=4)

        self.assertEqual(mock_global_log.warning.call_count, 0)

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None

        with open("agent_syslog.log", "r") as fp:
            actual = fp.read().strip()

        self.assertTrue(
            expected_line1 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_line1, actual),
        )
        self.assertTrue(
            expected_line2 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_line2, actual),
        )

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    def test_run_tcp_server(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
        }

        self.monitor = TestSyslogMonitor(config, self.logger)
        self.monitor.open_metric_log()

        self.monitor.start()
        time.sleep(0.05)

        s = socket.socket(socket.AF_INET)
        self.sockets.append(s)

        self.connect(s, ("localhost", 8514))

        expected_line1 = "TCP TestXX"
        self.send_and_wait_for_lines(s, expected_line1 + "\n")

        expected_line2 = "Line2"
        expected_line3 = "Line3"
        self.send_and_wait_for_lines(
            s, expected_line2 + "\n" + expected_line3 + "\n", expected_line_count=2
        )

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None

        f = open("agent_syslog.log", "r")
        actual = f.read().strip()

        self.assertTrue(
            expected_line1 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_line1, actual),
        )
        self.assertTrue(
            expected_line2 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_line2, actual),
        )
        self.assertTrue(
            expected_line2 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_line2, actual),
        )

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    def test_run_udp_server(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "udp:5514",
            "log_flush_delay": 0.0,
        }
        self.monitor = TestSyslogMonitor(
            config, scalyr_logging.getLogger("syslog_monitor[test]")
        )
        self.monitor.open_metric_log()
        self.monitor.start()

        time.sleep(0.1)

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockets.append(s)

        expected = "UDP Test %s" % (uuid.uuid4())
        self.send_and_wait_for_lines(s, expected, dest_addr=("localhost", 5514))

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None
        f = open("agent_syslog.log", "r")
        actual = f.read().strip()
        self.assertTrue(
            expected in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected, actual),
        )

    @mock.patch(
        "scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler", TestSyslogHandler
    )
    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    def test_run_multiple_servers(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "udp:8000, tcp:8001, udp:8002, tcp:8003",
            "log_flush_delay": 0.0,
        }
        self.monitor = TestSyslogMonitor(
            config, scalyr_logging.getLogger("syslog_monitor[test]")
        )
        self.monitor.open_metric_log()

        self.monitor.start()

        time.sleep(0.05)

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockets.append(udp)

        tcp1 = socket.socket()
        self.sockets.append(tcp1)

        tcp2 = socket.socket()
        self.sockets.append(tcp2)

        self.connect(tcp1, ("localhost", 8001))
        self.connect(tcp2, ("localhost", 8003))

        expected_udp1 = "UDP Test"
        self.send_and_wait_for_lines(udp, expected_udp1, ("localhost", 8000))

        expected_udp2 = "UDP2 Test"
        self.send_and_wait_for_lines(udp, expected_udp2, ("localhost", 8002))

        expected_tcp1 = "TCP Test\n"
        self.send_and_wait_for_lines(tcp1, expected_tcp1)

        expected_tcp2 = "TCP2 Test\n"
        self.send_and_wait_for_lines(tcp2, expected_tcp2)

        # without close, the logger will interfere with other test cases.
        self.monitor.close_metric_log()

        self.monitor.stop(wait_on_join=False)
        self.monitor = None

        f = open("agent_syslog.log", "r")
        actual = f.read().strip()

        expected_tcp1 = expected_tcp1.strip()
        expected_tcp2 = expected_tcp2.strip()

        self.assertTrue(
            expected_udp1 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_udp1, actual),
        )
        self.assertTrue(
            expected_udp2 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_udp2, actual),
        )
        self.assertTrue(
            expected_tcp1 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_tcp1, actual),
        )
        self.assertTrue(
            expected_tcp2 in actual,
            "Unable to find '%s' in output:\n\t %s" % (expected_tcp2, actual),
        )
