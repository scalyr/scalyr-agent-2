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


from scalyr_agent.builtin_monitors.shell_monitor import ShellMonitor
from scalyr_agent.test_base import ScalyrTestCase

import mock


class ShellMonitorTest(ScalyrTestCase):
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
