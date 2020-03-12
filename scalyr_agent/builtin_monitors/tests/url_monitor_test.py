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


from scalyr_agent.builtin_monitors.url_monitor import UrlMonitor
from scalyr_agent.test_base import ScalyrTestCase

import mock


class UrLMonitorTest(ScalyrTestCase):
    def test_gather_sample(self):
        monitor_config = {
            "module": "shell_monitor",
            "url": "https://www.scalyr.com",
            "request_method": "GET",
            "max_characters": 100,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(call_args[0], "response")
        self.assertTrue(len(call_args[1]) >= 10)
        self.assertEqual(call_kwargs["extra_fields"]["url"], "https://www.scalyr.com")
        self.assertEqual(call_kwargs["extra_fields"]["status"], 200)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")
