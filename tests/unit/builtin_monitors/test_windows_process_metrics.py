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

from scalyr_agent.builtin_monitors.windows_process_metrics import ProcessMonitor

__all__ = ["WindowsProcessMetricsMonitorTestCase"]


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
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        self.assertEqual(monitor._sample_interval_secs, 30)

        # 2. Custom interval overriden via monitor config option
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "sample_interval": 90,
        }
        monitor = ProcessMonitor(monitor_config, logger=mock_logger)
        self.assertEqual(monitor._sample_interval_secs, 90)

        # 3. Overriden via constructor argument (only when used programtically)
        monitor_config = {
            "module": "scalyr_agent.builtin_monitors.windows_process_metrics",
            "id": "id1",
            "sample_interval": 90,
        }
        monitor = ProcessMonitor(
            monitor_config, logger=mock_logger, sample_interval_secs=66
        )
        self.assertEqual(monitor._sample_interval_secs, 66)
