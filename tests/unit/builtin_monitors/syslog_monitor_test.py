# -*- coding: utf-8 -*-
# Copyright 2014-2022 Scalyr Inc.
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
# author: scalyr-cloudtech@scalyr.com

from __future__ import unicode_literals
from __future__ import absolute_import

from contextlib import contextmanager
from dataclasses import dataclass

if False:
    from typing import List

__author__ = "scalyr-cloudtech@scalyr.com"

import time
import sys
import socket
import unittest
import logging
import uuid
import os
import errno
from io import open
from io import StringIO
import threading
import platform

from scalyr_agent.builtin_monitors import syslog_monitor
from scalyr_agent.builtin_monitors.syslog_monitor import (
    SyslogMonitor,
    SyslogRequest,
    SocketNotReadyException,
    SyslogTCPServer,
    SyslogUDPServer,
)
from scalyr_agent.builtin_monitors.syslog_monitor import SyslogFrameParser
from scalyr_agent.builtin_monitors.syslog_monitor import SyslogRequestParser
from scalyr_agent.builtin_monitors.syslog_monitor import SyslogBatchedRequestParser
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.scalyr_monitor import MonitorInformation
from scalyr_agent.test_base import ScalyrTestCase
import scalyr_agent.scalyr_logging as scalyr_logging

import six
import mock

from scalyr_agent.test_base import skipIf

global_log = scalyr_logging.getLogger(__name__)


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


class SyslogMonitorThreadingTest(ScalyrTestCase):

    BIND_ADDRESS = "localhost"

    class RequestVerifierMock:
        def verify_request(self, client_address):
            return True

    VERIFIER = RequestVerifierMock()

    class SyslogHandlerMock:
        @dataclass
        class LogLine:
            timestamp: float
            data: str
            extra: dict

        def __init__(self, address, type, handling_time):
            self.logged_data = []
            self.address = address
            self.type = type
            self.handling_time = handling_time

        def handle(self, data, extra):
            self.logged_data.append(self.LogLine(time.time(), data, extra))
            time.sleep(self.handling_time)

    class MockConfig:
        def __init__(self):
            self.syslog_processing_thread_count = 4
            self.syslog_socket_thread_count = 4
            self.syslog_monitors_shutdown_grace_period = 1

    def __tcp_server(self, port, handling_time, global_config):
        server = SyslogTCPServer(
            port,
            tcp_buffer_size=50,
            bind_address=self.BIND_ADDRESS,
            verifier=self.VERIFIER,
            global_config=global_config,
        )
        server.syslog_handler = self.SyslogHandlerMock(
            server.socket.getsockname(), server.socket.type, handling_time
        )
        return server

    def __udp_server(self, port, handling_time, global_config):
        server = SyslogUDPServer(
            port,
            bind_address=self.BIND_ADDRESS,
            verifier=self.VERIFIER,
            global_config=global_config,
        )
        server.syslog_handler = self.SyslogHandlerMock(
            server.socket.getsockname(), server.socket.type, handling_time
        )
        return server

    @contextmanager
    def start_servers(
        self, udp_servers_count, tcp_servers_count, handling_time, global_config
    ):
        udp_servers = [
            self.__udp_server(0, handling_time, global_config)
            for _ in range(udp_servers_count)
        ]
        tcp_servers = [
            self.__tcp_server(0, handling_time, global_config)
            for _ in range(tcp_servers_count)
        ]

        threads = [
            threading.Thread(target=server.serve_forever)
            for server in udp_servers + tcp_servers
        ]

        for thread in threads:
            thread.start()

        yield udp_servers, tcp_servers

        for server in udp_servers + tcp_servers:
            server.shutdown()

        for thread in threads:
            thread.join(timeout=0.1)
            assert not thread.is_alive()

    @staticmethod
    def __send_syslog_messages(address, type, connections, messages_per_connection):
        def message(connection_n, message_n):
            message = f"<123> message-{connection_n, message_n}\n"
            return message

        def send():
            for i in range(connections):
                sock = socket.socket(socket.AF_INET, type)
                sock.connect(address)
                for j in range(messages_per_connection):
                    sock.send(message(i, j).encode())
                sock.close()

        t = threading.Thread(target=send)
        return t

    def test_without_global_config(self):
        with self.start_servers(
            udp_servers_count=1,
            tcp_servers_count=1,
            handling_time=0,
            global_config=None,
        ) as (udp_servers, tcp_servers):
            for server in tcp_servers:
                MESSAGES_PER_CONNECTION = 100
                CONNECTIONS = 10
                t = self.__send_syslog_messages(
                    server.socket.getsockname(),
                    server.socket.type,
                    connections=CONNECTIONS,
                    messages_per_connection=MESSAGES_PER_CONNECTION,
                )
                t.start()
                t.join()

                time.sleep(0.5)

                server.shutdown()
                server.server_close()

                for _ in range(100):
                    time.sleep(0.1)
                    if (
                        len(server.syslog_handler.logged_data)
                        == CONNECTIONS * MESSAGES_PER_CONNECTION
                    ):
                        break

                assert (
                    len(server.syslog_handler.logged_data)
                    == CONNECTIONS * MESSAGES_PER_CONNECTION
                )

    def test_shutdown_with_pending_requests(self):
        HANDLING_TIME = 0.1
        mock_config = self.MockConfig()
        with self.start_servers(
            udp_servers_count=0,
            tcp_servers_count=1,
            handling_time=HANDLING_TIME,
            global_config=mock_config,
        ) as (udp_servers, tcp_servers):
            for server in tcp_servers:
                MESSAGES_PER_CONNECTION = 300
                CONNECTIONS = 10
                t = self.__send_syslog_messages(
                    server.socket.getsockname(),
                    server.socket.type,
                    connections=CONNECTIONS,
                    messages_per_connection=MESSAGES_PER_CONNECTION,
                )
                t.start()
                t.join()

                time.sleep(0.5)

                server.shutdown()
                server.server_close()

                msg_count_before_grace_period_elapsed = len(
                    server.syslog_handler.logged_data
                )

                time.sleep(
                    mock_config.syslog_processing_thread_count * 10 * HANDLING_TIME + 3
                )

                msg_count_after_grace_period_elapsed = len(
                    server.syslog_handler.logged_data
                )

                assert (
                    msg_count_after_grace_period_elapsed
                    > msg_count_before_grace_period_elapsed
                )

                # Cancel futures introduced in 3.9
                if sys.version_info[0:2] >= (3, 9):
                    time.sleep(1)
                    # No new messages processed
                    assert (
                        len(server.syslog_handler.logged_data)
                        == msg_count_after_grace_period_elapsed
                    )

    def test_fair_workers_distribution(self):
        # Given
        udp_servers_count = 3
        tcp_servers_count = 3
        connections = 10
        messages_per_connection = 50
        handling_time = 0.01
        advantage_time = handling_time * 10
        message_window = (udp_servers_count + tcp_servers_count) * 15
        shutdown_time = connections * messages_per_connection * handling_time + 3

        with self.start_servers(
            udp_servers_count,
            tcp_servers_count,
            handling_time,
            global_config=self.MockConfig(),
        ) as (udp_servers, tcp_servers):
            # When
            # Send some data to the servers
            def send_data_to_servers(servers):
                threads = [
                    self.__send_syslog_messages(
                        server.socket.getsockname(),
                        server.socket.type,
                        connections,
                        messages_per_connection,
                    )
                    for server in servers
                ]

                for t in threads:
                    t.start()

                return threads

            def join_threads(threads):
                for t in threads:
                    t.join()

            threads_first = send_data_to_servers(udp_servers[:1] + tcp_servers[:1])
            time.sleep(advantage_time)
            threads_rest = send_data_to_servers(udp_servers[1:] + tcp_servers[1:])
            join_threads(threads_first + threads_rest)

            time.sleep(shutdown_time)

            shutdown_threads = [
                threading.Thread(target=server.shutdown)
                for server in udp_servers + tcp_servers
            ]
            for t in shutdown_threads:
                t.start()

            for t in shutdown_threads:
                t.join()

            # Then
            logged_port_timestamp_sorted = sorted(
                [
                    (server.socket.getsockname()[1], log_line.timestamp)
                    for server in udp_servers + tcp_servers
                    for log_line in server.syslog_handler.logged_data
                ],
                key=lambda x: x[1],
            )

            logged_port_sorted = [x[0] for x in logged_port_timestamp_sorted]

            # Check that the workers are distributed evenly
            for start in range(len(logged_port_sorted) // 2):
                print(len(set(logged_port_sorted[start : start + message_window])))
                assert len(
                    set(logged_port_sorted[start : start + message_window])
                ) == len(udp_servers + tcp_servers)


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

    def handle(self, data, extra):
        assert (
            type(data) == six.text_type
        ), "SyslogHandler.handle function accepts only unicode strings."
        return super(TestSyslogHandler, self).handle(data, extra)


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
    def test_run_tcp_server_small_tcp_buffer_size_message_size_can_exceed_tcp_buffer_false(
        self, mock_global_log
    ):
        # message_size_can_exceed_tcp_buffer size is False and tcp_buffer_size is 5 bytes. Timeout
        # should occur because partial data should be flushed before we receive a whole line
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_buffer_size": 5,
            "message_size_can_exceed_tcp_buffer": False,
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
    def test_run_tcp_server_small_tcp_buffer_size__message_size_can_exceed_tcp_buffer_true(
        self, mock_global_log
    ):
        # When message_size_can_exceed_tcp_buffer config option is set to True, we should support
        # messages which span multiple packets and are more than tcp_buffer_size in size
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_buffer_size": 5,
            "message_size_can_exceed_tcp_buffer": True,
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
    def test_run_tcp_server_batch_request_parser(self):
        config = {
            "module": "scalyr_agent.builtin_monitors.syslog_monitor",
            "protocols": "tcp:8514",
            "log_flush_delay": 0.0,
            "tcp_request_parser": "batch",
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


class SyslogDefaultRequestParserTestCase(SyslogMonitorTestCase):
    @mock.patch("scalyr_agent.builtin_monitors.syslog_monitor.global_log")
    def test_internal_buffer_and_offset_is_reset_on_handler_method_call_no_data(
        self, mock_global_log
    ):
        # Verify internal buffer and offset is reset after handling the frame
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        parser = SyslogRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        self.assertEqual(parser._remaining, None)

        self.assertEqual(mock_global_log.warning.call_count, 0)
        parser.process(None)
        self.assertEqual(mock_handle_frame.call_count, 0)
        self.assertEqual(mock_global_log.warning.call_count, 1)
        self.assertEqual(parser._remaining, None)

        parser.process(b"")
        self.assertEqual(mock_handle_frame.call_count, 0)
        self.assertEqual(parser._remaining, None)

    def test_internal_buffer_and_offset_is_reset_on_handler_method_call_single_complete_message(
        self,
    ):
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-0-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"

        parser = SyslogRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        self.assertEqual(parser._remaining, None)

        parser.process(mock_msg_1)
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_msg_1[:-1],
        )

        # Verify internal state is correctly reset
        self.assertEqual(parser._remaining, bytearray())
        self.assertEqual(parser._offset, 0)

    def test_process_success_no_existing_buffer_recv_multiple_complete_messages(self):
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_2 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_3 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_data = mock_msg_1 + mock_msg_2 + mock_msg_3

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # Ensure we only call handle_frame once with all the data
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]), mock_data[:-1]
        )

        # Verify internal state is correctly reset
        self.assertEqual(parser._remaining, bytearray())
        self.assertEqual(parser._offset, 0)

    def test_process_success_no_existing_buffer_recv_multiple_complete_messages_invalid_utf8_data(
        self,
    ):
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        invalid_utf8_data = "ž".encode("utf-16")

        mock_msg_1 = (
            b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle %s, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
            % (invalid_utf8_data)
        )
        mock_msg_2 = (
            b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle %s, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
            % (invalid_utf8_data)
        )
        mock_msg_3 = (
            b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle %s, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
            % (invalid_utf8_data)
        )
        mock_data = mock_msg_1 + mock_msg_2 + mock_msg_3

        # byte sequence which falls outside of utf-8 range should be ignored
        mock_msg_1_expected = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle ~\x01, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_2_expected = b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle ~\x01, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_3_expected = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle ~\x01, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"

        parser = SyslogRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # Ensure handle_frame has been called once per message
        self.assertEqual(mock_handle_frame.call_count, 3)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_msg_1_expected.strip(),
        )
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[1][0][0]),
            mock_msg_2_expected.strip(),
        )
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[2][0][0]),
            mock_msg_3_expected.strip(),
        )

        # Verify internal state is correctly reset
        self.assertEqual(parser._remaining, bytearray())
        self.assertEqual(parser._offset, 0)


class SyslogTCPRequestParserTestCase(SyslogMonitorTestCase):
    def test_eagain_is_handled_correctly(self):
        mock_socket = mock.Mock()

        def mock_socket_recv(buffer_size=1024):
            mock_socket_recv.counter += 1

            if mock_socket_recv.counter < 3:
                raise socket.error(errno.EAGAIN, "EAGAIN")

            return "data1"

        mock_socket_recv.counter = 0
        mock_socket.recv = mock_socket_recv

        reader = SyslogRequest(socket=mock_socket, max_buffer_size=64)

        self.assertRaises(SocketNotReadyException, reader.read)
        self.assertEqual(mock_socket_recv.counter, 1)
        self.assertRaises(SocketNotReadyException, reader.read)
        self.assertEqual(mock_socket_recv.counter, 2)
        self.assertEqual(reader.read(), "data1")
        self.assertEqual(mock_socket_recv.counter, 3)

    @skipIf(sys.version_info < (3, 0, 0), "Skipping under Python 2")
    def test_eagain_is_handled_correctly_python3(self):
        mock_socket = mock.Mock()

        def mock_socket_recv(buffer_size=1024):
            mock_socket_recv.counter += 1

            if mock_socket_recv.counter < 3:
                raise BlockingIOError("EAGAIN")

            return "data2"

        mock_socket_recv.counter = 0
        mock_socket.recv = mock_socket_recv

        reader = SyslogRequest(
            socket=mock_socket,
            max_buffer_size=64,
        )
        self.assertRaises(SocketNotReadyException, reader.read)
        self.assertEqual(mock_socket_recv.counter, 1)
        self.assertRaises(SocketNotReadyException, reader.read)
        self.assertEqual(mock_socket_recv.counter, 2)
        self.assertEqual(reader.read(), "data2")
        self.assertEqual(mock_socket_recv.counter, 3)


class SyslogBatchRequestParserTestCase(SyslogMonitorTestCase):
    @mock.patch("scalyr_agent.builtin_monitors.syslog_monitor.global_log")
    def test_process_success_no_data(self, mock_global_log):
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )

        self.assertEqual(mock_global_log.warning.call_count, 0)
        parser.process(None)
        self.assertEqual(mock_handle_frame.call_count, 0)
        self.assertEqual(mock_global_log.warning.call_count, 1)
        parser.process(b"")
        self.assertEqual(mock_handle_frame.call_count, 0)

    def test_process_success_no_existing_buffer_recv_single_complete_message(self):
        # Here we emulate receving a single message in a single recv call (which is quite unlikely
        # to happen often in real life)
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-0-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_msg_1)
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_msg_1[:-1],
        )
        self.assertEqual(parser._remaining, bytearray())

    def test_process_success_no_existing_buffer_recv_multiple_complete_messages(self):
        # Here we emulate multiple complete messages returned in a single recv call
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_2 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_3 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_data = mock_msg_1 + mock_msg_2 + mock_msg_3

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # Ensure we only call handle_frame once with all the data
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]), mock_data[:-1]
        )
        self.assertEqual(parser._remaining, bytearray())

    def test_process_success_no_existing_buffer_recv_multiple_messages_some_partial(
        self,
    ):
        # Here we emulate recv returning partial data and ensuring it's handled correctly
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_2 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_3 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"
        mock_msg_4 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"

        mock_data = mock_msg_1 + mock_msg_2 + mock_msg_3[: int(len(mock_msg_3) / 2)]

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # Ensure we only call handle_frame. Since last message was incomplete, only first two
        # messages should have been flushed and part of the 3rd one should still be in internal
        # buffer
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_msg_1 + mock_msg_2[:-1],
        )

        self.assertEqual(parser._remaining, mock_msg_3[: int(len(mock_msg_3) / 2)])

        # Now emulate rest of the message 3 + complete message 4 arriving
        mock_data = mock_msg_3[int(len(mock_msg_3) / 2) :] + mock_msg_4

        parser.process(mock_data)
        self.assertEqual(mock_handle_frame.call_count, 2)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[1][0][0]),
            mock_msg_3 + mock_msg_4[:-1],
        )

        self.assertEqual(parser._remaining, bytearray())

    @mock.patch("scalyr_agent.builtin_monitors.syslog_monitor.global_log")
    def test_process_no_frame_data_timeout_reached_flush_partial(self, mock_global_log):
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n"

        mock_data = mock_msg_1[: int(len(mock_msg_1) / 2)]

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            incomplete_frame_timeout=1,
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # No complete frame
        self.assertEqual(mock_handle_frame.call_count, 0)
        self.assertEqual(mock_global_log.warning.call_count, 0)

        # Wait for timeout to be reached
        time.sleep(2)

        # We have not seen a complete frame / message yet, but a timeout has been reached so what
        # we have seen so far should be flushed.
        parser.process(b"a")
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_data + b"a",
        )
        self.assertEqual(mock_global_log.warning.call_count, 1)

    def test_process_null_character_custom_delimiter(self):
        # Here we emulate recv returning partial data and ensuring it's handled correctly when
        # utilizing a custom delimiter character
        mock_socket = mock.Mock()
        mock_handle_frame = mock.Mock()
        max_buffer_size = 1024

        mock_msg_1 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-1-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\000"
        mock_msg_2 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-2-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\000"
        mock_msg_3 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\000"
        mock_msg_4 = b"<14>Dec 24 16:12:48 hosttest.example.com tag-3-0-17[2593]: Hey diddle diddle, The Cat and the Fiddle, The Cow jump'd over the Spoon\n\000"

        mock_data = mock_msg_1 + mock_msg_2 + mock_msg_3[: int(len(mock_msg_3) / 2)]

        parser = SyslogBatchedRequestParser(
            socket_client_address=("127.0.0.1", 1234),
            socket_server_address=("127.0.0.2", 5678),
            max_buffer_size=max_buffer_size,
            message_delimiter="\000",
            handle_frame=mock_handle_frame,
        )
        parser.process(mock_data)

        # Ensure we only call handle_frame. Since last message was incomplete, only first two
        # messages should have been flushed and part of the 3rd one should still be in internal
        # buffer
        self.assertEqual(mock_handle_frame.call_count, 1)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[0][0][0]),
            mock_msg_1[:-1] + b"\n" + mock_msg_2[:-1],
        )

        self.assertEqual(parser._remaining, mock_msg_3[: int(len(mock_msg_3) / 2)])

        # Now emulate rest of the message 3 + complete message 4 arriving
        mock_data = mock_msg_3[int(len(mock_msg_3) / 2) :] + mock_msg_4

        parser.process(mock_data)
        self.assertEqual(mock_handle_frame.call_count, 2)
        self.assertEqual(
            six.ensure_binary(mock_handle_frame.call_args_list[1][0][0]),
            mock_msg_3[:-1] + b"\n" + mock_msg_4[:-2],
        )

        self.assertEqual(parser._remaining, bytearray())
