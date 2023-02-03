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
from scalyr_agent.configuration import Configuration
from scalyr_agent.json_lib import JsonObject
from scalyr_agent import scalyr_logging 
from scalyr_agent.test_base import ScalyrTestCase

# Replace with unittest.mock when only supporting Python >= 3.3
import mock

import collections
import os.path
import socket
import threading
import time

class SyslogMonitorMock(SyslogMonitor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert not hasattr(self, 'lines') and not hasattr(self, 'lines_cond')
        self.lines = 0
        self.lines_cond = threading.Condition()

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

captures = collections.defaultdict(list)
captures_lock = threading.Lock()

# SyslogHandler instances are attributes of SyslogServer instances which are private attributes of SyslogMonitor.
# Because of this patching SyslogHandler methods and retaining original behavior isn't feasible without abusing private attribute access.
class SyslogHandlerMock(SyslogHandler):
    def handle(self, data, extra):
        super().handle(data, extra)
        # FIXME STOPPED Make the values here available for verification
        #print('*'*10, repr(data), extra)

class ConfigurationMock(Configuration):
    log_path = '.'

    def __init__(self, log_configs):
        self.mock_log_configs = log_configs

    @property
    def log_configs(self):
        return self.mock_log_configs
    
    @property
    def agent_log_path(self):
        return self.__class__.log_path

    @property
    def server_attributes(self):
        return {"serverHost":"localhost"}

    @property
    def log_rotation_backup_count(self):
        return 2

    @property
    def log_rotation_max_bytes(self):
        return 20 * 1024 * 1024

# Capture generated log filenames and prevent file creations/writes.
class AutoFlushingRotatingFileMock:
    def __init__(self, filename, **kwargs):
        with captures_lock:
            captures['filenames'].append(filename)

    def write(self, message):
        pass

    def flush(self):
        pass

# Capture main log filename and prevent file creation/writes.
class AutoFlushingRotatingFileHandlerMock:
    def __init__(self, filename, **kwargs):
        with captures_lock:
            captures['filenames'].append(filename)
    
    def flush(self):
        pass

@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFile', AutoFlushingRotatingFileMock)
@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFileHandler', AutoFlushingRotatingFileHandlerMock)
@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.SyslogHandler', SyslogHandlerMock)
class SyslogTemplateTest(ScalyrTestCase):
    port = 1601

    def setUp(self):
        super().setUp()
        self.monitor = None

        global captures
        with captures_lock:
            captures = collections.defaultdict(list)

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
        global_config = ConfigurationMock([
            {
                'path': os.path.join(ConfigurationMock.log_path, 'syslog*.log'), 
                'attributes': JsonObject({ 'parser': 'syslog-parser' }),
            }
        ])

        logger = scalyr_logging.getLogger(self.__class__.__name__)
        self.monitor = SyslogMonitorMock(config, logger, global_config=global_config)
        self.monitor.open_metric_log()
        self.monitor.start()

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        with captures_lock:
            self.assertEqual(captures['filenames'], ['agent_syslog.log', './syslog.log'])

    def test_no_params_no_logs(self):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocols': 'tcp:%d' % self.__class__.port,
            'message_log_template': 'syslog.log',
        }
        global_config = ConfigurationMock([])

        logger = scalyr_logging.getLogger(self.__class__.__name__)
        self.monitor = SyslogMonitorMock(config, logger, global_config=global_config)
        self.monitor.open_metric_log()
        self.monitor.start()

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        with captures_lock:
            self.assertEqual(captures['filenames'], ['agent_syslog.log'])

    def test_no_params_no_matching_logs(self):
        config = {
            'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
            'protocols': 'tcp:%d' % self.__class__.port,
            'message_log_template': 'syslog.log',
        }
        global_config = ConfigurationMock([
            {
                'path': os.path.join(ConfigurationMock.log_path, 'not-syslog*.log'), 
                'attributes': JsonObject({ 'parser': 'not-syslog-parser' }),
            }
        ])

        logger = scalyr_logging.getLogger(self.__class__.__name__)
        self.monitor = SyslogMonitorMock(config, logger, global_config=global_config)
        self.monitor.open_metric_log()
        self.monitor.start()

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        with captures_lock:
            self.assertEqual(captures['filenames'], ['agent_syslog.log'])

    # FIXME Options to test: message_log_template, check_for_unused_logs_mins, delete_unused_logs_hours, max_log_files
    # FIXME Test substitutions of message_log_template for "PROTO", "SRCIP", "DESTPORT", "HOSTNAME", "APPNAME"
    # FIXME Test all other aspects of __handle_syslog_logs(data, extra), pull in master for previous PR change
