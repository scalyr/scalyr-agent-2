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

from __future__ import unicode_literals

from scalyr_agent.builtin_monitors.syslog_monitor import (
    RUN_EXPIRE_COUNT,
    SyslogHandler,
    SyslogMonitor,
)
from scalyr_agent.configuration import Configuration
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent import scalyr_logging
from scalyr_agent.test_base import ScalyrTestCase, skip, skipIf

# Replace with unittest.mock when only supporting Python >= 3.3
import mock

import copy
import logging
import os.path
import platform
import socket
import sys
import threading
import time


class SyslogMonitorMock(SyslogMonitor):
    def __init__(self, *args, **kwargs):
        super(SyslogMonitorMock, self).__init__(*args, **kwargs)
        assert not hasattr(self, "lines") and not hasattr(self, "lines_cond")
        self.lines = 0
        self.lines_cond = threading.Condition()

    def increment_counter(self, reported_lines=0, **kwargs):
        super(SyslogMonitorMock, self).increment_counter(reported_lines, **kwargs)
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


class ConfigurationMock(Configuration):
    log_path = "."

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
        return {"serverHost": "localhost"}

    @property
    def log_rotation_backup_count(self):
        return 2

    @property
    def log_rotation_max_bytes(self):
        return 20 * 1024 * 1024

    @property
    def syslog_processing_thread_count(self):
        return 4

    @property
    def syslog_socket_thread_count(self):
        return 4

    @property
    def syslog_monitors_shutdown_grace_period(self):
        return 1


class LogWatcherMock(LogWatcher):
    def __init__(self):
        self.log_configs = []

    def add_log_config(self, monitor_name, log_config):
        assert monitor_name == "scalyr_agent.builtin_monitors.syslog_monitor"

        log_config_copy = copy.deepcopy(log_config)
        log_config_copy["attributes"] = log_config_copy["attributes"].to_dict()
        self.log_configs.append(log_config_copy)

        return log_config

    def remove_log_path(self, monitor_name, log_path):
        assert monitor_name == "scalyr_agent.builtin_monitors.syslog_monitor"

        for idx, log_config in enumerate(self.log_configs):
            if log_config["path"] == log_path:
                self.log_configs.pop(idx)
                return
        raise Exception("not found")


# Mocked to prevent file creations/writes (for message_log_template log files)
class AutoFlushingRotatingFileMock:
    def __init__(self, *args, **kwargs):
        pass

    def write(self, message):
        pass

    def flush(self):
        pass

    def close(self):
        pass


# Mocked to prevent file creations/writes (for the main log file)
class AutoFlushingRotatingFileHandlerMock:
    def __init__(self, *args, **kwargs):
        self.level = logging.INFO

    def flush(self):
        pass

    def handle(self, record):
        pass

    def setFormatter(self, *args, **kwargs):
        pass


@skipIf(
    platform.system() == "Windows" or sys.version_info < (3, 6, 0),
    "Skipping tests due to dependency requirements",
)
@mock.patch(
    "scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFile",
    AutoFlushingRotatingFileMock,
)
@mock.patch(
    "scalyr_agent.builtin_monitors.syslog_monitor.AutoFlushingRotatingFileHandler",
    AutoFlushingRotatingFileHandlerMock,
)
class SyslogTemplateTest(ScalyrTestCase):
    tcp_port = 1601
    udp_port = 1514

    def setUp(self):
        super(SyslogTemplateTest, self).setUp()
        self.monitor = None
        self.watcher = None

    def tearDown(self):
        super(SyslogTemplateTest, self).tearDown()
        if self.monitor:
            self.monitor.stop()

    def create_monitor(self, config, log_configs):
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
        data,
        port=None,
        proto=socket.SOCK_STREAM,
        bind_addr=None,
        timeout=3,
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
                sock.connect(("127.0.0.1", port))
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
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n")
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 1)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )

    def test_no_params_no_logs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog.log",
            },
            [],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n")
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 0)

    def test_no_params_no_matching_logs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "not-syslog*.log"),
                    "attributes": JsonObject({"parser": "not-syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n")
        self.monitor.wait_until_count(1)

        self.assertEqual(len(self.watcher.log_configs), 0)

    def test_proto_destport_params_one_logconfig(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d, udp:%d"
                % (self.__class__.tcp_port, self.__class__.udp_port),
                "message_log_template": "syslog-${PROTO}-${DESTPORT}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n",
            self.__class__.tcp_port,
            socket.SOCK_STREAM,
        )
        self.monitor.wait_until_count(1)
        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n",
            self.__class__.udp_port,
            socket.SOCK_DGRAM,
        )
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-tcp-%d.log" % self.__class__.tcp_port,
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-udp-%d.log" % self.__class__.udp_port,
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "udp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.udp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )

    def test_proto_destport_param_two_logconfigs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d, tcp:%d"
                % (self.__class__.tcp_port, self.__class__.tcp_port + 1),
                "message_log_template": "syslog-${PROTO}-${DESTPORT}.log",
            },
            [
                {
                    "path": os.path.join(
                        ConfigurationMock.log_path,
                        "syslog-tcp-%d.log" % self.__class__.tcp_port,
                    ),
                    "attributes": JsonObject({"parser": "first-parser"}),
                },
                {
                    "path": os.path.join(
                        ConfigurationMock.log_path,
                        "syslog-tcp-%d.log" % (self.__class__.tcp_port + 1,),
                    ),
                    "attributes": JsonObject({"parser": "second-parser"}),
                },
            ],
        )

        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n",
            self.__class__.tcp_port,
        )
        self.monitor.wait_until_count(1)
        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n",
            self.__class__.tcp_port + 1,
        )
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-tcp-%d.log" % self.__class__.tcp_port,
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "first-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-tcp-%d.log" % (self.__class__.tcp_port + 1,),
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port + 1,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "second-parser",
            },
        )

    # On Debian based distros `localhost 127.0.1.1` is added to /etc/hosts
    @skip("Requires aliasing the loopback interface")
    def test_srcip_param(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${SRCIP}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                },
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost demo[1]: hello world\n",
            bind_addr="127.0.1.1",
        )
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-127.0.0.1.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-127.0.1.1.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.2",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )

    def test_hostname_param_one_logconfig(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${HOSTNAME}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 alpha demo[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 bravo demo[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-alpha.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "alpha",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-bravo.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "bravo",
                    "appname": "demo",
                },
                "parser": "syslog-parser",
            },
        )

    def test_hostname_param_two_explicit_logconfigs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${HOSTNAME}.log",
            },
            [
                {
                    "path": os.path.join(
                        ConfigurationMock.log_path, "syslog-alpha.log"
                    ),
                    "attributes": JsonObject({"parser": "first-parser"}),
                },
                {
                    "path": os.path.join(
                        ConfigurationMock.log_path, "syslog-bravo.log"
                    ),
                    "attributes": JsonObject({"parser": "second-parser"}),
                },
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 alpha demo[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 bravo demo[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-alpha.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "alpha",
                    "appname": "demo",
                },
                "parser": "first-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-bravo.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "bravo",
                    "appname": "demo",
                },
                "parser": "second-parser",
            },
        )

    def test_hostname_param_two_globbed_logconfigs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${HOSTNAME}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-a*.log"),
                    "attributes": JsonObject({"parser": "first-parser"}),
                },
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-b*.log"),
                    "attributes": JsonObject({"parser": "second-parser"}),
                },
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 alpha demo[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 bravo demo[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-alpha.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "alpha",
                    "appname": "demo",
                },
                "parser": "first-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-bravo.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "bravo",
                    "appname": "demo",
                },
                "parser": "second-parser",
            },
        )

    def test_hostname_param_two_logconfigs_fallthrough(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${HOSTNAME}.log",
            },
            [
                {
                    "path": os.path.join(
                        ConfigurationMock.log_path, "syslog-alpha.log"
                    ),
                    "attributes": JsonObject({"parser": "first-parser"}),
                },
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "second-parser"}),
                },
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 alpha demo[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 bravo demo[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-alpha.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "alpha",
                    "appname": "demo",
                },
                "parser": "first-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-bravo.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "bravo",
                    "appname": "demo",
                },
                "parser": "second-parser",
            },
        )

    def test_appname_param_one_logconfig(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${APPNAME}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost apiserver[1]: hello world\n"
        )
        self.monitor.wait_until_count(1)
        self.connect_and_send(
            b"<1>Jan 02 12:34:56 localhost database[1]: hello world\n"
        )
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-apiserver.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "apiserver",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-database.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "database",
                },
                "parser": "syslog-parser",
            },
        )

    def test_multiple_attribs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${APPNAME}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject(
                        {
                            "parser": "syslog-parser",
                            "source-type": "internal",
                        }
                    ),
                }
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app1[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app2[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-app1.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "app1",
                    "source-type": "internal",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-app2.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "app2",
                    "source-type": "internal",
                },
                "parser": "syslog-parser",
            },
        )

    def test_multiple_attribs_two_logconfigs(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${APPNAME}.log",
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-app1.log"),
                    "attributes": JsonObject(
                        {
                            "parser": "syslog-parser",
                            "source-type": "internal",
                        }
                    ),
                },
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-app2.log"),
                    "attributes": JsonObject(
                        {
                            "parser": "syslog-parser",
                            "source-type": "external",
                        }
                    ),
                },
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app1[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app2[1]: hello world\n")
        self.monitor.wait_until_count(2)

        self.assertEqual(len(self.watcher.log_configs), 2)
        self.assertDictEqual(
            self.watcher.log_configs[0],
            {
                "path": "./syslog-app1.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "app1",
                    "source-type": "internal",
                },
                "parser": "syslog-parser",
            },
        )
        self.assertDictEqual(
            self.watcher.log_configs[1],
            {
                "path": "./syslog-app2.log",
                "attributes": {
                    "monitor": "agentSyslog",
                    "proto": "tcp",
                    "srcip": "127.0.0.1",
                    "destport": self.__class__.tcp_port,
                    "hostname": "localhost",
                    "appname": "app2",
                    "source-type": "external",
                },
                "parser": "syslog-parser",
            },
        )

    def test_max_log_files(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${APPNAME}.log",
                "max_log_files": 3,
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        template = "<1>Jan 02 12:34:56 localhost app%d[1]: hello world\n"
        for i in range(5):
            self.connect_and_send((template % i).encode("utf-8"))
            self.monitor.wait_until_count(i + 1)

        self.assertEqual(len(self.watcher.log_configs), 3)
        for i in range(3):
            self.assertDictEqual(
                self.watcher.log_configs[i],
                {
                    "path": "./syslog-app%d.log" % i,
                    "attributes": {
                        "monitor": "agentSyslog",
                        "proto": "tcp",
                        "srcip": "127.0.0.1",
                        "destport": self.__class__.tcp_port,
                        "hostname": "localhost",
                        "appname": "app%d" % i,
                    },
                    "parser": "syslog-parser",
                },
            )

    def test_expire_log(self):
        self.create_monitor(
            {
                "module": "scalyr_agent.builtin_monitors.syslog_monitor",
                "protocols": "tcp:%d" % self.__class__.tcp_port,
                "message_log_template": "syslog-${APPNAME}.log",
                "expire_log": 1,
            },
            [
                {
                    "path": os.path.join(ConfigurationMock.log_path, "syslog-*.log"),
                    "attributes": JsonObject({"parser": "syslog-parser"}),
                }
            ],
        )

        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app1[1]: hello world\n")
        self.monitor.wait_until_count(1)
        self.connect_and_send(b"<1>Jan 02 12:34:56 localhost app2[1]: hello world\n")
        self.monitor.wait_until_count(2)
        self.assertEqual(len(self.watcher.log_configs), 2)

        time.sleep(1)
        self.connect_and_send(
            b"".join(
                [b"<1>Jan 02 12:34:56 localhost app2[1]: hello world\n"]
                * RUN_EXPIRE_COUNT
            )
        )
        self.monitor.wait_until_count(2 + RUN_EXPIRE_COUNT)
        self.assertEqual(len(self.watcher.log_configs), 1)


@skipIf(
    platform.system() == "Windows" or sys.version_info < (3, 6, 0),
    "Skipping tests due to dependency requirements",
)
class SyslogParserTest(ScalyrTestCase):
    def test_rfc3164_example1(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8"
            ),
            {"hostname": "mymachine", "appname": "su"},
        )

    @skip("current parser does not handle a missing appname correctly")
    def test_rfc3164_example2(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog("<13>Feb  5 17:32:18 10.0.0.99 Use the BFG!"),
            {"hostname": "10.0.0.99", "appname": None},
        )

    @skip("current parser does not parse this timestamp format correctly")
    def test_rfc3164_example3(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<165>Aug 24 05:34:00 CST 1987 mymachine myproc[10]: %% It's time to make the do-nuts.  %%  Ingredients: Mix=OK, Jelly=OK # Devices: Mixer=OK, Jelly_Injector=OK, Frier=OK # Transport: Conveyer1=OK, Conveyer2=OK # %%"
            ),
            {"hostname": "mymachine", "appname": "myproc"},
        )

    @skip("current parser does not parse this timestamp format correctly")
    def test_rfc3164_example4(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<0>1990 Oct 22 10:52:01 TZ-6 scapegoat.dmz.example.org 10.1.2.3 sched[0]: That's All Folks!"
            ),
            {"hostname": "10.1.2.3", "appname": "sched"},
        )

    @skip(
        "current parser does not parse this timestamp format correctly nor removes leading spaces from appname"
    )
    def test_syslog_collector_cisco1(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<113>Nov 14 2022 09:13:13 vFTD  %FTD-1-430003: EventPriority: Low, DeviceUUID: 8792c90e-a3c8-11eb-9d9a-9813adfd688a, InstanceID: 2, FirstPacketSecond: 2022-11-14T09:13:13Z, ConnectionID: 19501, AccessControlRuleAction: Allow, SrcIP: 10.1.149.14, DstIP: 97.86.238.25, SrcPort: 59370, DstPort: 59963, Protocol: udp, IngressInterface: TG-Inside, EgressInterface: TG-Outside, IngressZone: TG-Inside, EgressZone: TG-Outside, IngressVRF: Global, EgressVRF: Global, ACPolicy: CSTA-vFTD, AccessControlRuleName: All-in-One, Prefilter Policy: Default Prefilter Policy, Client: BitTorrent, ApplicationProtocol: BitTorrent, ConnectionDuration: 0, InitiatorPackets: 1, ResponderPackets: 0, InitiatorBytes: 143, ResponderBytes: 0, NAPPolicy: Balanced Security and Connectivity"
            ),
            {"hostname": "vFTD", "appname": "%FTD-1-430003"},
        )

    def test_syslog_collector_cisco1_mod(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<113>Nov 14 09:13:13 vFTD %FTD-1-430003: EventPriority: Low, DeviceUUID: 8792c90e-a3c8-11eb-9d9a-9813adfd688a, InstanceID: 2, FirstPacketSecond: 2022-11-14T09:13:13Z, ConnectionID: 19501, AccessControlRuleAction: Allow, SrcIP: 10.1.149.14, DstIP: 97.86.238.25, SrcPort: 59370, DstPort: 59963, Protocol: udp, IngressInterface: TG-Inside, EgressInterface: TG-Outside, IngressZone: TG-Inside, EgressZone: TG-Outside, IngressVRF: Global, EgressVRF: Global, ACPolicy: CSTA-vFTD, AccessControlRuleName: All-in-One, Prefilter Policy: Default Prefilter Policy, Client: BitTorrent, ApplicationProtocol: BitTorrent, ConnectionDuration: 0, InitiatorPackets: 1, ResponderPackets: 0, InitiatorBytes: 143, ResponderBytes: 0, NAPPolicy: Balanced Security and Connectivity"
            ),
            {"hostname": "vFTD", "appname": "%FTD-1-430003"},
        )

    @skip(
        "current parser does not parse this timestamp format correctly nor handles the extra colon"
    )
    def test_syslog_collector_cisco2(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<166>2022-11-14T10:03:35Z ftd : %FTD-6-302015: Built inbound UDP connection 29258504 for Inside:10.180.10.25/123 (198.18.133.254/123) to Outside:163.172.150.183/123 (163.172.150.183/123)"
            ),
            {"hostname": "ftd", "appname": "%FTD-1-302015"},
        )

    def test_syslog_collector_cisco2_mod(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<166>Nov 14 10:03:35 ftd %FTD-6-302015: Built inbound UDP connection 29258504 for Inside:10.180.10.25/123 (198.18.133.254/123) to Outside:163.172.150.183/123 (163.172.150.183/123)"
            ),
            {"hostname": "ftd", "appname": "%FTD-6-302015"},
        )

    @skip(
        "current parser does not parse this timestamp format correctly nor handles the extra colon"
    )
    def test_syslog_collector_cisco3(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<166>2022-11-14T10:03:33Z ftd : %FTD-6-302014: Teardown TCP connection 29258492 for Inside:10.180.10.215/17756 to Outside:169.254.169.254/80 duration 0:00:30 bytes 0 SYN Timeout"
            ),
            {"hostname": "ftd", "appname": "%FTD-1-302015"},
        )

    def test_syslog_collector_cisco3_mod(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                "<166>Nov 14 10:03:33 ftd %FTD-6-302014: Teardown TCP connection 29258492 for Inside:10.180.10.215/17756 to Outside:169.254.169.254/80 duration 0:00:30 bytes 0 SYN Timeout"
            ),
            {"hostname": "ftd", "appname": "%FTD-6-302014"},
        )

    @skip(
        "current parser does not parse this timestamp format correctly nor handles the extra colon"
    )
    def test_syslog_collector_cisco4(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                '<164>2022-11-14T10:03:26Z ftd : %FTD-4-106023: Deny tcp src Outside:198.144.159.104/50010 dst Inside:10.180.10.25/28132 by access-group "CSM_FW_ACL_" [0x97aa021a, 0x0]'
            ),
            {"hostname": "ftd", "appname": "%FTD-1-302015"},
        )

    def test_syslog_collector_cisco4_mod(self):
        self.assertDictEqual(
            SyslogHandler._parse_syslog(
                '<164>Nov 14 10:03:26 ftd %FTD-4-106023: Deny tcp src Outside:198.144.159.104/50010 dst Inside:10.180.10.25/28132 by access-group "CSM_FW_ACL_" [0x97aa021a, 0x0]'
            ),
            {"hostname": "ftd", "appname": "%FTD-4-106023"},
        )
