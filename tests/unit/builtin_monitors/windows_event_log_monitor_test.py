# Copyright 2011-2022 Scalyr Inc.
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
import sys

import scalyr_agent.builtin_monitors.windows_event_log_monitor
from scalyr_agent.builtin_monitors.windows_event_log_monitor import (
    WindowEventLogMonitor,
)

from scalyr_agent.test_base import ScalyrTestCase


@pytest.mark.windows_platform
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

    def test_newjsonapi_backwards_compatible(self):
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
        }
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        mock_logger = mock.Mock()

        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        self.assertTrue(
            isinstance(
                monitor._WindowEventLogMonitor__api,
                scalyr_agent.builtin_monitors.windows_event_log_monitor.NewApi,
            )
        )

        if sys.platform == "Windows":
            monitor_config["json"] = True

            monitor = WindowEventLogMonitor(monitor_config, mock_logger)
            self.assertTrue(
                isinstance(
                    monitor._WindowEventLogMonitor__api,
                    scalyr_agent.builtin_monitors.windows_event_log_monitor.NewJsonApi,
                )
            )

    def test_convert_json_array_to_object(self):
        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                ["a", "b", "c"]
            ),
            {"0": "a", "1": "b", "2": "c"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                ["a", ["b1", "b2"], "c"]
            ),
            {"0": "a", "1": {"0": "b1", "1": "b2"}, "2": "c"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                {"a": "aa", "b": "bb", "c": "cc"}
            ),
            {"a": "aa", "b": "bb", "c": "cc"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                {"a": "aa", "b": ["b1", "b2"], "c": "cc"}
            ),
            {"a": "aa", "b": {"0": "b1", "1": "b2"}, "c": "cc"},
        )

    def test_strip_xmltodict_prefixes(self):
        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                {"@a": "a", "#text": "t"}
            ),
            {"a": "a", "Text": "t"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                {"@a": "a", "a": "b"}
            ),
            {"@a": "a", "a": "b"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                {"a": "b", "@a": "a"}
            ),
            {"@a": "a", "a": "b"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                {"#text": "t", "Text": "b"}
            ),
            {"#text": "t", "Text": "b"},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                {"@a": "a", "b": {"@b": "b"}}
            ),
            {"a": "a", "b": {"b": "b"}},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._strip_xmltodict_prefixes(
                [{"@a": "a", "#text": "t"}]
            ),
            [{"a": "a", "Text": "t"}],
        )
