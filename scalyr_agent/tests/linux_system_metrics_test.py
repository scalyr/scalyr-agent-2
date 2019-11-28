# Copyright 2017 Scalyr Inc.
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

__author__ = 'echee@scalyr.com'

from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.tests.configuration_test import TestConfigurationBase
from scalyr_agent.test_util import FakePlatform


class TestSystemMetricConfiguration(TestConfigurationBase):

    def test_log_write_rate(self):
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.linux_system_metrics",
                    "monitor_log_write_rate": -1,
                    "monitor_log_max_write_burst": -1
                }
            ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        test_manager = MonitorsManager(config, FakePlatform([]))
        system_metrics_monitor = test_manager.monitors[0]
        self.assertEquals(system_metrics_monitor._log_write_rate, -1)
        self.assertEquals(system_metrics_monitor._log_max_write_burst, -1)

