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

from __future__ import absolute_import
from __future__ import unicode_literals

import mock

from scalyr_agent.test_base import ScalyrTestCase

from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.builtin_monitors.windows_process_metrics import ProcessMonitor

__all__ = ["WindowsProcessMetricsMonitorTestCase"]


class MockNoSuchProcess(Exception):
    pass


class WindowsProcessMetricsMonitorTestCase(ScalyrTestCase):
    @mock.patch(
        "scalyr_agent.builtin_monitors.windows_process_metrics.psutil", mock.Mock()
    )
    def test_custom_sample_interval(self):
        mock_logger = mock.Mock()

        # 1. Default interval
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "pid": "$$",
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        self.assertEqual(monitor._sample_interval_secs, 30)

        # 2. Custom interval overriden via monitor config option
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "pid": "$$",
            "sample_interval": 90,
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        self.assertEqual(monitor._sample_interval_secs, 90)

        # 3. Overriden via constructor argument (only when used programtically)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "pid": "$$",
            "sample_interval": 90,
        }
        monitor = ProcessMonitor(
            monitor_config, logger=mock_logger, sample_interval_secs=66
        )
        self.assertEqual(monitor._sample_interval_secs, 66)

    def test_error_is_thrown_on_invalid_config(self):
        mock_logger = mock.Mock()

        # 1. neither pid nor commandline is specified
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "sample_interval": 90,
        }

        expected_msg = r'Either "pid" or "commandline" monitor config option needs to be specified \(but not both\)'
        self.assertRaisesRegex(
            BadMonitorConfiguration,
            expected_msg,
            ProcessMonitor,
            monitor_config,
            logger=mock_logger,
            sample_interval_secs=66,
        )

        # 2. both arguments are specified
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "pid": "$$",
            "commandline": "apache",
            "sample_interval": 90,
        }

        expected_msg = r'Either "pid" or "commandline" monitor config option needs to be specified \(but not both\)'
        self.assertRaisesRegex(
            BadMonitorConfiguration,
            expected_msg,
            ProcessMonitor,
            monitor_config,
            logger=mock_logger,
            sample_interval_secs=66,
        )

    @mock.patch("scalyr_agent.builtin_monitors.windows_process_metrics.psutil")
    @mock.patch("scalyr_agent.builtin_monitors.windows_process_metrics.global_log")
    def test_process_not_found_warning_is_logged(self, mock_global_log, mock_psutil):
        mock_psutil.NoSuchProcess = MockNoSuchProcess
        mock_logger = mock.Mock()

        # 1. pid specified
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "pid": "$$",
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        monitor._select_target_process = mock.Mock(
            side_effect=MockNoSuchProcess("error")
        )

        self.assertEqual(mock_global_log.warn.call_count, 0)
        monitor.gather_sample()
        mock_global_log.warn.assert_called_with('Unable to find process with pid "$$"')
        self.assertEqual(mock_global_log.warn.call_count, 1)

        # 2. commandline specified
        mock_global_log.reset_mock()
        mock_logger.reset_mock()

        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "commandline": "apache",
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        monitor._select_target_process = mock.Mock(
            side_effect=MockNoSuchProcess("error")
        )

        self.assertEqual(mock_global_log.warn.call_count, 0)
        monitor.gather_sample()
        mock_global_log.warn.assert_called_with(
            'Unable to find process with commandline "apache"'
        )
        self.assertEqual(mock_global_log.warn.call_count, 1)
