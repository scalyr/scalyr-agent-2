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

from __future__ import absolute_import

import mock

from scalyr_agent.test_base import ScalyrTestCase

from scalyr_agent.builtin_monitors.windows_system_metrics import _gather_metric
from scalyr_agent.builtin_monitors.windows_system_metrics import __NO_DISK_PERF__

__all__ = ["WindowsSystemMetricsMonitorTestCase"]


class WindowsSystemMetricsMonitorTestCase(ScalyrTestCase):
    @mock.patch("scalyr_agent.builtin_monitors.windows_system_metrics.methodcaller")
    def test_gather_metrics_diskperf_not_available(self, mock_methodcaller):
        mock_methodcaller.side_effect = RuntimeError("couldn't find any physical disk")
        result = list(_gather_metric(method="disk_io_counters")())

        self.assertEqual(result[0][0], __NO_DISK_PERF__)

        mock_methodcaller.side_effect = AttributeError(
            "'NoneType' object has no attribute 'read_bytes'"
        )
        result = list(_gather_metric(method="disk_io_counters")())

        self.assertEqual(result[0][0], __NO_DISK_PERF__)
