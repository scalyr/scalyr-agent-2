# Copyright 2014-2020 Scalyr Inc.
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
from __future__ import absolute_import

import os
import sys
import platform

import mock

try:
    import psutil
except ImportError:
    psutil = None

from scalyr_agent.builtin_monitors.linux_process_metrics import ProcessMonitor
from scalyr_agent.scalyr_monitor import load_monitor_class
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

__all__ = ["LinuxProcessMetricsMonitorTest"]


class LinuxProcessMetricsMonitorTest(ScalyrTestCase):
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    @skipIf(
        not psutil,
        "Skipping tests because psutil is not available (likely running under Python 3.6 on Circle CI)",
    )
    def test_gather_sample_by_pid_success(self):
        monitor_config = {
            "module": "linux_process_metrics",
            "id": "my-id",
            "pid": os.getpid(),
        }
        mock_logger = mock.Mock()
        monitor = ProcessMonitor(monitor_config, mock_logger)

        monitor_module = "scalyr_agent.builtin_monitors.linux_process_metrics"
        monitor_info = load_monitor_class(monitor_module, [])[1]

        monitor.gather_sample()

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, len(monitor_info.metrics))

    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    @skipIf(
        not psutil,
        "Skipping tests because psutil is not available (likely running under Python 2.6 on Circle CI)",
    )
    def test_gather_sample_by_commandline_success(self):
        monitor_config = {
            "module": "linux_process_metrics",
            "id": "my-id",
            "commandline": ".*%s.*" % (" ".join(sys.argv)),
        }
        mock_logger = mock.Mock()
        monitor = ProcessMonitor(monitor_config, mock_logger)

        monitor_module = "scalyr_agent.builtin_monitors.linux_process_metrics"
        monitor_info = load_monitor_class(monitor_module, [])[1]

        monitor.gather_sample()

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(mock_logger.emit_value.call_count, len(monitor_info.metrics))

    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    @skipIf(
        not psutil,
        "Skipping tests because psutil is not available (likely running under Python 2.6 on Circle CI)",
    )
    def test_gather_sample_by_pid_failure_pid_doesnt_exist(self):
        monitor_config = {
            "module": "linux_process_metrics",
            "id": "my-id",
            "pid": 65555,
        }
        mock_logger = mock.Mock()
        monitor = ProcessMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        self.assertEqual(mock_logger.error.call_count, 3)
        self.assertEqual(mock_logger.emit_value.call_count, 0)
