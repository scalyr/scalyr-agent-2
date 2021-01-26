# Copyright 2014-2021 Scalyr Inc.
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

import os
import time
import platform

import six

from scalyr_agent.builtin_monitors.linux_process_metrics import ProcessTracker
from scalyr_agent.metrics_collector import PSUtilProcessTracker
from scalyr_agent.builtin_monitors.linux_process_metrics import Metric

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf


class PSUtilProcessTrackerTestCase(ScalyrTestCase):
    def test_psutil_tracker_collect_metrics(self):
        pid = os.getpid()
        tracker = PSUtilProcessTracker(pid, None, None)

        expected_metrics = [
            Metric("app.cpu", "user"),
            Metric("app.cpu", "system"),
            Metric("app.uptime", None),
            Metric("app.threads", None),
            Metric("app.mem.bytes", "resident"),
            Metric("app.mem.bytes", "vmsize"),
            Metric("app.mem.bytes", "resident_shared"),
            Metric("app.mem.bytes", "resident_private"),
            Metric("app.disk.requests", "read"),
            Metric("app.disk.requests", "write"),
            Metric("app.disk.bytes", "read"),
            Metric("app.disk.bytes", "write"),
            Metric("app.io.wait", None),
        ]

        result = tracker.collect()

        for expected_metric in expected_metrics:
            self.assertTrue(
                expected_metric in result, "%s not found in result" % (expected_metric)
            )
            value = result[expected_metric]
            self.assertTrue(value >= 0)

    @skipIf(
        platform.system() != "Linux", "Skipping Linux only tests on other platforms"
    )
    def test_psutil_and_linux_process_tracker(self):
        """
        Test that PSUtilProcessTracker and Linux-only ProcessTracker return same metrics value.

        Due to some of those metrics having very high resolution and because we can't run both
        collectors at exactly the same time, we allow for some variance in the results and still
        consider it as correct.
        """

        pid = os.getpid()
        linux_tracker = ProcessTracker(pid, None, None)
        psutil_tracker = PSUtilProcessTracker(pid, None, None)

        # We sleep for 2 seconds to ensure uptime metrics increased
        time.sleep(2.5)

        result_linux_tracker = linux_tracker.collect()
        result_psutil_tracker = psutil_tracker.collect()

        # Those metrics are not available via Linux monitor so we skip them
        ignored_metrics = [
            Metric("app.disk.bytes", "read"),
            Metric("app.disk.bytes", "write"),
            Metric("app.mem.bytes", "resident_shared"),
            Metric("app.mem.bytes", "resident_private"),
        ]

        for metric, value in six.iteritems(result_psutil_tracker):
            if metric in ignored_metrics:
                continue

            other_value = result_linux_tracker[metric]

            upper_threshold = value * 1.2
            lower_threshold = value * 0.8

            # Special case for uptime since linux monitor has millisecond resolution and cross
            # platform psutil only has second resolution. We basically ignore the ms fraction
            if metric == Metric("app.uptime", None):
                other_value = int((other_value) / 1000) * 1000

            if (
                value != other_value
                and other_value < lower_threshold
                or other_value > upper_threshold
            ):
                self.fail(
                    "Got value %s for metric %s, expected %s +/- 20%%"
                    % (other_value, metric, value)
                )
