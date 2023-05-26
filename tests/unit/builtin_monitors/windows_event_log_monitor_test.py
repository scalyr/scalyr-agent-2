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
import os
import pytest
import sys
import tempfile

if sys.platform == "Windows":
    import scalyr_agent.builtin_monitors.windows_event_log_monitor
    from scalyr_agent.builtin_monitors.windows_event_log_monitor import (
        WindowEventLogMonitor,
    )
    import win32api  # pylint: disable=import-error
    import win32con  # pylint: disable=import-error

import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase, ScalyrTestCase
from scalyr_agent.test_base import skipIf


def _get_parameter_msg_fixture_path():
    unit_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(unit_dir, "fixtures", "parametermsgfixture.dll")


@pytest.mark.windows_platform
class WindowsEventLogMonitorTest(ScalyrTestCase):
    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
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

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
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

        monitor_config["json"] = True

        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        self.assertTrue(
            isinstance(
                monitor._WindowEventLogMonitor__api,
                scalyr_agent.builtin_monitors.windows_event_log_monitor.NewJsonApi,
            )
        )

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
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

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                [{"a": 1, "b": 2}, {"c": 3, "d": 4}]
            ),
            {"0": {"a": 1, "b": 2}, "1": {"c": 3, "d": 4}},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                [{"a": 1, "b": 2, "@Name": "n"}, {"c": 3, "d": 4}]
            ),
            {"n": {"a": 1, "b": 2}, "1": {"c": 3, "d": 4}},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                [{"a": 1, "b": 2, "@Name": "n"}, {"c": 3, "d": 4, "@Name": "n"}]
            ),
            {"n": {"a": 1, "b": 2}, "n1": {"c": 3, "d": 4}},
        )

        self.assertEqual(
            scalyr_agent.builtin_monitors.windows_event_log_monitor._convert_json_array_to_object(
                [
                    {"a": 1, "@Name": "n"},
                    {"b": 2, "@Name": "n2"},
                    {"c": 3, "@Name": "n"},
                ]
            ),
            {"n": {"a": 1}, "n2": {"b": 2}, "2": {"c": 3, "@Name": "n"}},
        )

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
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

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
    @mock.patch(
        "scalyr_agent.builtin_monitors.windows_event_log_monitor._DLL.dllpath",
        return_value=_get_parameter_msg_fixture_path(),
    )
    def test_replace_param_placeholders(self, *args):
        # pylint: disable=no-member
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
            "json": True,
        }
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        mock_logger = mock.Mock()

        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        test_events = [
            {
                "Event": {
                    "System": {
                        "Channel": "System",
                        "Provider": {"Name": "SomethingSilly"},
                    },
                    "EventData": {"Data": "%%392"},
                },
            },
            {
                "Event": {
                    "System": {
                        "Channel": "System",
                        "Provider": {"Name": "SomethingSilly"},
                    },
                    "EventData": {
                        "Data": {
                            "One": "%%553",
                            "Two": {"Text": "%%990"},
                            "Three": {"Text": "%%69"},
                        }
                    },
                },
            },
        ]

        result = monitor._replace_param_placeholders(test_events[0])
        self.assertEqual(result["Event"]["EventData"]["Data"], "blarg")

        result = monitor._replace_param_placeholders(test_events[1])
        self.assertEqual(result["Event"]["EventData"]["Data"]["One"], "honk")
        self.assertEqual(result["Event"]["EventData"]["Data"]["Two"]["Text"], "rawr")
        self.assertEqual(result["Event"]["EventData"]["Data"]["Three"]["Text"], "Nice")

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
    @mock.patch(
        "scalyr_agent.builtin_monitors.windows_event_log_monitor._DLL.dllpath",
        return_value=_get_parameter_msg_fixture_path(),
    )
    def test_param_placeholder_value_resolution(self, *args):
        # pylint: disable=no-member
        monitor_config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
            "json": True,
        }
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        mock_logger = mock.Mock()

        monitor = WindowEventLogMonitor(monitor_config, mock_logger)
        value = monitor._param_placeholder_value("MyChannel", "MyProvider", "%%392")
        self.assertEqual(value, "blarg")
        value = monitor._param_placeholder_value("MyChannel", "MyProvider", "%%553")
        self.assertEqual(value, "honk")
        value = monitor._param_placeholder_value("MyChannel", "MyProvider", "%%990")
        self.assertEqual(value, "rawr")
        value = monitor._param_placeholder_value("MyChannel", "MyProvider", "%%69")
        self.assertEqual(value, "Nice")
        value = monitor._param_placeholder_value("MyChannel", "MyProvider", "%%1111")
        self.assertEqual(value, "all your base are belong to us")

    @skipIf(sys.platform != "Windows", "Skipping tests under non-Windows platform")
    def test_parameter_msg_file_location_lookup(self):
        msgDLL = _get_parameter_msg_fixture_path()
        channel = "Application"
        provider = "Scalyr-Agent-Test"

        # Create registry entry with known value
        hkey = win32api.RegCreateKey(
            win32con.HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Services\\EventLog\\%s\\%s"
            % (channel, provider),
        )
        win32api.RegSetValueEx(
            hkey,
            "ParameterMessageFile",  # value name \
            0,  # reserved \
            win32con.REG_EXPAND_SZ,  # value type \
            msgDLL,
        )
        win32api.RegCloseKey(hkey)

        # Ensure any mocks on `_DLL.dllpath` were cleaned up
        self.assertFalse(
            isinstance(
                scalyr_agent.builtin_monitors.windows_event_log_monitor._DLL.dllpath,
                mock.Mock,
            )
        )
        value = scalyr_agent.builtin_monitors.windows_event_log_monitor._DLL.dllpath(
            channel, provider
        )
        self.assertEqual(value, msgDLL)

        # Cleanup
        win32api.RegDeleteKey(
            win32con.HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Services\\EventLog\\%s\\%s"
            % (channel, provider),
        )


@pytest.mark.windows_platform
class WindowsEventLogMonitorTest2(BaseScalyrLogCaptureTestCase):
    @skipIf(
        sys.platform not in ["Windows", "win32"],
        "Skipping tests under non-Windows platform",
    )
    def test_newjsonapi_with_no_rate_limit(self):
        config = {
            "module": "windows_event_log_monitor",
            "sources": "Application, Security, System",
            "event_types": "All",
            "json": True,
            "monitor_log_write_rate": -1,
            "monitor_log_max_write_burst": -1,
        }

        metric_file_fd, metric_file_path = tempfile.mkstemp(config["module"] + ".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        logger = scalyr_logging.getLogger(config["module"])
        scalyr_agent.builtin_monitors.windows_event_log_monitor.windll = mock.Mock()
        monitor = WindowEventLogMonitor(config, logger)
        monitor.log_config["path"] = metric_file_path

        # Normally called when the monitor is started (via MonitorsManager.__start_monitor)
        monitor.open_metric_log()

        logger.emit_value("unused", '{"foo":"bar"}')

        self.assertEquals(monitor.reported_lines(), 1)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="foo"
        )

        logger.closeMetricLog()
