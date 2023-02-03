# Copyright 2023 Scalyr Inc.
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

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogHandler, SyslogMonitor
from scalyr_agent.monitor_utils import AutoFlushingRotatingFile
from scalyr_agent import scalyr_logging 
from scalyr_agent.scalyr_logging import AutoFlushingRotatingFileHandler
from scalyr_agent.test_base import ScalyrTestCase

# Replace with unittest.mock when only supporting Python >= 3.3
import mock

import socket
import threading
import time

class SyslogMonitorMock(SyslogMonitor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert not hasattr(self, 'lines') and not hasattr(self, 'lines_cond')
        self.lines, self.lines_cond = 0, threading.Condition()

    def increment_counter(self, reported_lines=0, **kwargs):
        super().increment_counter(reported_lines, **kwargs)
        with self.lines_cond:
            self.lines += reported_lines
            self.lines_cond.notify()

    def wait_until_count(self, count, timeout=3):
        with self.lines_cond:
            while self.lines != count:
                start = time.time()
                if not self.lines_cond.wait(timeout):
                    raise TimeoutError
                timeout -= time.time() - start

# SyslogHandler instances are attributes of SyslogServer instances which are private attributes of SyslogMonitor.
# Because of this patching SyslogHandler methods and retaining original behavior isn't feasible without abusing private attribute access.
class SyslogHandlerMock(SyslogHandler):
    def handle(self, data, extra):
        super().handle(data, extra)
        # FIXME STOPPED Make the values here available for verification
        print('*'*10, repr(data), extra)

# Capture generated log filenames and prevent creation/writes in SyslogHandler.__handle_syslog
class AutoFlushingRotatingFileMock(AutoFlushingRotatingFile):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        # FIXME STOPPED Make filename available here for verification
        print('*'*10, filename)

    def _open(self, *args, **kwargs):
        pass
    
    def write(self, *args, **kwargs):
        pass

# Prevent log creation in SyslogMonitor.open_metric_log
class AutoFlushingRotatingFileHandlerMock(AutoFlushingRotatingFileHandler):
    def __init__(self, *args, **kwargs):
        pass

@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler', SyslogHandlerMock)
@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFile', AutoFlushingRotatingFileMock)
@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFileHandler', AutoFlushingRotatingFileHandlerMock)
class SyslogTemplateTest(ScalyrTestCase):
    port = 1601

    def setUp(self):
        super().setUp()
        self.monitor = None

    def tearDown(self):
        super().tearDown()
        if self.monitor:
            self.monitor.stop()

    @staticmethod
    def connect_and_send(data: bytes, port: int=None, timeout=3):
        port = port or SyslogTemplateTest.port

        timedout = time.time() + timeout
        while time.time() < timedout:
            try:
                # If a connect fails, the state of the socket is unspecified.
                # Hence not attempting to reuse the socket here.
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(('127.0.0.1', port))
                sock.sendall(data)
                return
            except ConnectionRefusedError:
                time.sleep(0.1)
            finally:
                sock.close()
        raise TimeoutError

    def test_no_params(self):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocols': 'tcp:%d' % self.__class__.port,
            'message_log_template': 'syslog.log',
        }
        logger = scalyr_logging.getLogger(self.__class__.__name__)

        self.monitor = SyslogMonitorMock(config, logger)
        self.monitor.open_metric_log()
        self.monitor.start()

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        # FIXME Options to test: message_log_template, check_for_unused_logs_mins, delete_unused_logs_hours, max_log_files
        # FIXME Test substitutions of message_log_template for "PROTO", "SRCIP", "DESTPORT", "HOSTNAME", "APPNAME"
        # FIXME Test all other aspects of __handle_syslog_logs(data, extra), pull in master for previous PR change
