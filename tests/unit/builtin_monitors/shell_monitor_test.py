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
# ------------------------------------------------------------------------
#
# author: Edward Chee <echee@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

import platform

import mock

from scalyr_agent.builtin_monitors.shell_monitor import ShellMonitor
from scalyr_agent.test_base import ScalyrTestCase

from scalyr_agent.test_base import skipIf


class ShellMonitorTest(ScalyrTestCase):
    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    def test_gather_sample(self):
        monitor_config = {
            "module": "shell_monitor",
            "command": 'echo "foo bar!"',
            "max_characters": 200,
        }
        mock_logger = mock.Mock()
        monitor = ShellMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args, ("output", "foo bar!"))
        self.assertEqual(call_kwargs["extra_fields"]["command"], 'echo "foo bar!"')
        self.assertEqual(call_kwargs["extra_fields"]["length"], 9)

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    def test_gather_sample_max_characters_output_trimming(self):
        monitor_config = {
            "module": "shell_monitor",
            "command": 'echo "foo bar!"',
            "max_characters": 3,
        }
        mock_logger = mock.Mock()
        monitor = ShellMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args, ("output", "foo..."))
        self.assertEqual(call_kwargs["extra_fields"]["command"], 'echo "foo bar!"')
        self.assertEqual(call_kwargs["extra_fields"]["length"], 9)

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    def test_gather_sample_log_all_lines(self):
        monitor_config = {
            "module": "shell_monitor",
            "command": 'echo "line 1\nline 2\nline 3"',
            "max_characters": 100,
            "log_all_lines": True,
        }
        mock_logger = mock.Mock()
        monitor = ShellMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args, ("output", "line 1\nline 2\nline 3\n"))
        self.assertEqual(
            call_kwargs["extra_fields"]["command"], 'echo "line 1\nline 2\nline 3"'
        )
        self.assertEqual(call_kwargs["extra_fields"]["length"], 21)

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    def test_gather_sample_extract_expression(self):
        monitor_config = {
            "module": "shell_monitor",
            "command": 'echo "line 1\nline 2\nline 100\nline 200"',
            "extract": r"line (\d\d\d)",
            "max_characters": 100,
        }
        mock_logger = mock.Mock()
        monitor = ShellMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args, ("output", "100"))
        self.assertEqual(
            call_kwargs["extra_fields"]["command"],
            'echo "line 1\nline 2\nline 100\nline 200"',
        )
        self.assertEqual(call_kwargs["extra_fields"]["length"], 3)

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    def test_gather_sample_stdout_and_stderr_is_combined(self):
        monitor_config = {
            "module": "shell_monitor",
            "command": 'echo "stdout" ; >&2 echo "stderr"',
            "extract": r"line (\d\d\d)",
            "max_characters": 100,
            "log_all_lines": True,
        }
        mock_logger = mock.Mock()
        monitor = ShellMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args, ("output", "stderr\n\nstdout\n"))
        self.assertEqual(
            call_kwargs["extra_fields"]["command"], 'echo "stdout" ; >&2 echo "stderr"',
        )
        self.assertEqual(call_kwargs["extra_fields"]["length"], 15)
