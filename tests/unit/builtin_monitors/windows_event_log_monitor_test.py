# Copyright 2011 Scalyr Inc.
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

import mock

import scalyr_agent.builtin_monitors.windows_event_log_monitor
from scalyr_agent.builtin_monitors.windows_event_log_monitor import (
    WindowEventLogMonitor,
)

from scalyr_agent.test_base import ScalyrTestCase


class WindowsEventLogMonitorTest(ScalyrTestCase):
    def test_emit_warning_on_maximum_records_per_source_config_option_new_api(self):
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security",
            "event_types": "None",
            "maximum_records_per_source": 100,
        }

        # 1. OldApi - no warning emitted
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = None

        mock_logger = mock.Mock()

        self.assertEqual(mock_logger.info.call_count, 0)
        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        monitor._check_and_emit_info_and_warning_messages()
        self.assertEqual(mock_logger.info.call_count, 1)
        mock_logger.info.assert_called_with(
            "Evt API not detected.  Using older EventLog API"
        )

        # 2. NewApi, default records_per_source - no warning emitted
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
        }
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        mock_logger = mock.Mock()

        self.assertEqual(mock_logger.info.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        monitor._check_and_emit_info_and_warning_messages()
        self.assertEqual(mock_logger.info.call_count, 1)
        self.assertEqual(mock_logger.warn.call_count, 0)

        # 3. NewApi, non default records_per_source - warning emitted
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
            "maximum_records_per_source": 10,
        }
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        mock_logger = mock.Mock()

        self.assertEqual(mock_logger.info.call_count, 0)
        self.assertEqual(mock_logger.warn.call_count, 0)
        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        monitor._check_and_emit_info_and_warning_messages()
        self.assertEqual(mock_logger.info.call_count, 1)
        self.assertEqual(mock_logger.warn.call_count, 1)
        mock_logger.warn.assert_called_with(
            '"maximum_records_per_source" config option is set to '
            "a non-default value (10). This config option has no "
            "affect when using new evt API."
        )
