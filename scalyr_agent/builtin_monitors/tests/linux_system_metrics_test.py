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

import sys
import time

from scalyr_agent.builtin_monitors.linux_system_metrics import SystemMetricsMonitor
from scalyr_agent.scalyr_monitor import load_monitor_class
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

import mock
import platform

__all__ = ["LinuxSystemMetricsMonitorTest"]


class LinuxSystemMetricsMonitorTest(ScalyrTestCase):
    @skipIf(sys.version_info < (2, 7, 0), "Skipping tests under Python 2.6")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_gather_sample_success(self):
        monitor_config = {
            "module": "linux_system_metrics",
        }
        mock_logger = mock.Mock()
        monitor = SystemMetricsMonitor(monitor_config, mock_logger)

        monitor_module = "scalyr_agent.builtin_monitors.linux_system_metrics"
        monitor_info = load_monitor_class(monitor_module, [])[1]

        monitor.setDaemon(True)
        monitor.start()

        # Give it some time to spawn collectors and collect metrics
        time.sleep(2)
        monitor.stop()

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertTrue(mock_logger.info.call_count > len(monitor_info.metrics))

        # Verify all the metrics have been dispatched
        seen_metrics = set()
        for call_args in mock_logger.info.call_args_list:
            line = call_args[0][0]
            split = line.split(" ")
            metric_name = split[0]

            if "." not in metric_name:
                # Not a metric
                continue

            seen_metrics.add(metric_name)

        self.assertTrue(len(seen_metrics) >= len(monitor_info.metrics))

        for metric in monitor_info.metrics:
            metric_name = metric.metric_name
            self.assertTrue(
                metric_name in seen_metrics, "metric %s not seen" % (metric_name)
            )
