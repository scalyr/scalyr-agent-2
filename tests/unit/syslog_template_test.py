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

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogMonitor
from scalyr_agent.configuration import Configuration
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent import scalyr_logging 
from scalyr_agent.test_base import ScalyrTestCase, skip

# Replace with unittest.mock when only supporting Python >= 3.3
import mock

import copy
import os.path
import socket
import threading
import time
from typing import Any, Dict, List

class SyslogMonitorMock(SyslogMonitor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert not hasattr(self, 'lines') and not hasattr(self, 'lines_cond')
        self.lines = 0
        self.lines_cond = threading.Condition()

    def increment_counter(self, reported_lines: int=0, **kwargs):
        super().increment_counter(reported_lines, **kwargs)
        with self.lines_cond:
            self.lines += reported_lines
            self.lines_cond.notify()

    def wait_until_count(self, count: int, timeout: int=3):
        with self.lines_cond:
            while self.lines != count:
                start = time.time()
                if not self.lines_cond.wait(timeout):
                    raise TimeoutError
                timeout -= time.time() - start

class ConfigurationMock(Configuration):
    log_path = '.'

    def __init__(self, log_configs: List[Dict[str, Any]]):
        self.mock_log_configs = log_configs

    @property
    def log_configs(self) -> List[Dict[str, Any]]:
        return self.mock_log_configs
    
    @property
    def agent_log_path(self) -> str:
        return self.__class__.log_path

    @property
    def server_attributes(self) -> Dict[str, Any]:
        return {"serverHost":"localhost"}

    @property
    def log_rotation_backup_count(self) -> int:
        return 2

    @property
    def log_rotation_max_bytes(self) -> int:
        return 20 * 1024 * 1024

class LogWatcherMock(LogWatcher):
    def __init__(self):
        self.log_configs = []
    
    def add_log_config(self, monitor_name: str, log_config: Dict[str, Any]):
        assert monitor_name == 'scalyr_agent.builtin_monitors.syslog_monitor'

        log_config_copy = copy.deepcopy(log_config)
        log_config_copy['attributes'] = log_config_copy['attributes'].to_dict()
        self.log_configs.append(log_config_copy)

# Mocked to prevent file creations/writes (for message_log_template log files)
class AutoFlushingRotatingFileMock:
    def __init__(self, *args, **kwargs):
        pass

    def write(self, message):
        pass

    def flush(self):
        pass

# Mocked to prevent file creations/writes (for the main log file)
class AutoFlushingRotatingFileHandlerMock:
    def __init__(self, *args, **kwargs):
        pass
    
    def flush(self):
        pass

@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFile', AutoFlushingRotatingFileMock)
@mock.patch('scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFileHandler', AutoFlushingRotatingFileHandlerMock)
class SyslogTemplateTest(ScalyrTestCase):
    tcp_port = 1601
    udp_port = 1514

    def setUp(self):
        super().setUp()
        self.monitor = None
        self.watcher = None

    def tearDown(self):
        super().tearDown()
        if self.monitor:
            self.monitor.stop()

    def create_monitor(self, config: Dict[str, Any], log_configs: List[Dict[str, Any]]):
        self.monitor = SyslogMonitorMock(
            config,
            scalyr_logging.getLogger(self.__class__.__name__),
            global_config=ConfigurationMock(log_configs),
        )

        self.watcher = LogWatcherMock()
        self.monitor.set_log_watcher(self.watcher)

        self.monitor.open_metric_log()
        self.monitor.start()

    @staticmethod
    def connect_and_send(
        data: bytes,
        port: int=None,
        proto: socket.SocketKind=socket.SOCK_STREAM,
        bind_addr: str=None,
        timeout: int=3
    ):
        port = port or SyslogTemplateTest.tcp_port

        timedout = time.time() + timeout
        while time.time() < timedout:
            try:
                # If a connect fails, the state of the socket is unspecified.
                # Hence not attempting to reuse the socket here.
                sock = socket.socket(socket.AF_INET, proto)
                if bind_addr:
                    sock.bind((bind_addr, 0))
                sock.connect(('127.0.0.1', port))
                sock.sendall(data)
                return
            except ConnectionRefusedError:
                time.sleep(0.1)
            finally:
                sock.close()
        raise TimeoutError

    def test_no_params(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d' % self.__class__.tcp_port,
                'message_log_template': 'syslog.log',
            },
            [
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'syslog*.log'), 
                    'attributes': JsonObject({ 'parser': 'syslog-parser' }),
                }
            ],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 1)
        self.assertDictEqual(
            self.watcher.log_configs[0], 
            {
                'path': './syslog.log',
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.tcp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'syslog-parser',
            }
        )

    def test_no_params_no_logs(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d' % self.__class__.tcp_port,
                'message_log_template': 'syslog.log',
            },
            [],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 0)

    def test_no_params_no_matching_logs(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d' % self.__class__.tcp_port,
                'message_log_template': 'syslog.log',
            },
            [
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'not-syslog*.log'), 
                    'attributes': JsonObject({ 'parser': 'not-syslog-parser' }),
                }
            ],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello world\n')
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 0)

    def test_proto_destport_params_one_logconfig(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d, udp:%d' % (self.__class__.tcp_port, self.__class__.udp_port),
                'message_log_template': 'syslog-${PROTO}-${DESTPORT}.log',
            },
            [
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'syslog-*.log'), 
                    'attributes': JsonObject({ 'parser': 'syslog-parser' }),
                }
            ],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello tcp\n', self.__class__.tcp_port, socket.SOCK_STREAM)
        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello udp\n', self.__class__.udp_port, socket.SOCK_DGRAM)
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0], 
            {
                'path': './syslog-tcp-%d.log' % self.__class__.tcp_port,
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.tcp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'syslog-parser',
            }
        )
        self.assertDictEqual(
            self.watcher.log_configs[1], 
            {
                'path': './syslog-udp-%d.log' % self.__class__.udp_port,
                'attributes': {
                    'proto': 'udp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.udp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'syslog-parser',
            }
        )

    def test_destport_param_two_logconfigs(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d, tcp:%d' % (self.__class__.tcp_port, self.__class__.tcp_port + 1),
                'message_log_template': 'syslog-${PROTO}-${DESTPORT}.log',
            },
            [
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'syslog-tcp-%d.log' % self.__class__.tcp_port), 
                    'attributes': JsonObject({ 'parser': 'first-parser' }),
                },
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'syslog-tcp-%d.log' % (self.__class__.tcp_port + 1,)), 
                    'attributes': JsonObject({ 'parser': 'second-parser' }),
                },
            ],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello first\n', self.__class__.tcp_port)
        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello second\n', self.__class__.tcp_port + 1)
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0], 
            {
                'path': './syslog-tcp-%d.log' % self.__class__.tcp_port,
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.tcp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'first-parser',
            }
        )
        self.assertDictEqual(
            self.watcher.log_configs[1], 
            {
                'path': './syslog-tcp-%d.log' % (self.__class__.tcp_port + 1,),
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.tcp_port + 1,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'second-parser',
            }
        )

    @skip('Requires aliasing loopback interface on macOS') # FIXME Test on linux
    def test_srcip_param(self):
        self.create_monitor(
            {
                'module': 'scalyr_agent.builtin_monitors.syslog_monitor',
                'protocols': 'tcp:%d' % self.__class__.tcp_port,
                'message_log_template': 'syslog-${SRCIP}.log',
            },
            [
                {
                    'path': os.path.join(ConfigurationMock.log_path, 'syslog-*.log'), 
                    'attributes': JsonObject({ 'parser': 'syslog-parser' }),
                },
            ],
        )

        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello from localhost\n')
        self.connect_and_send(b'<1>Jan 02 12:34:56 localhost demo[1]: hello again from localhost\n', bind_addr='127.0.0.2')
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0], 
            {
                'path': './syslog-127.0.0.1.log',
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.1',
                    'destport': self.__class__.tcp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'syslog-parser',
            }
        )
        self.assertDictEqual(
            self.watcher.log_configs[1], 
            {
                'path': './syslog-127.0.0.2.log',
                'attributes': {
                    'proto': 'tcp',
                    'srcip': '127.0.0.2',
                    'destport': self.__class__.tcp_port,
                    'hostname': 'localhost',
                    'appname': 'demo'
                },
                'parser': 'syslog-parser',
            }
        )

    # FIXME Test substitutions of message_log_template for "HOSTNAME", "APPNAME"
    # FIXME Options to test: check_for_unused_logs_mins, delete_unused_logs_hours, max_log_files
    # FIXME Test all other aspects of __handle_syslog_logs(data, extra)
    # FIXME Test watcher.remove_log_path calls
    # FIXME Test SyslogHandler._parse_syslog
