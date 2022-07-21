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

import mock

from scalyr_agent.timing import get_empty_stats_dict
from scalyr_agent.timing import reset_stats_dict
from scalyr_agent.timing import record_timing_stats_for_function_call

from scalyr_agent.test_base import ScalyrTestCase


class TimingModuleTestCase(ScalyrTestCase):
    def test_get_empty_stats_dict(self):
        stats_dict = get_empty_stats_dict()
        self.assertEqual(stats_dict["min"], float("+inf"))
        self.assertEqual(stats_dict["max"], float("-inf"))
        self.assertEqual(stats_dict["count"], 0)
        self.assertEqual(stats_dict["sum"], 0)

    def test_reset_stats_dict(self):
        stats_dict = get_empty_stats_dict()
        stats_dict["count"] = 20
        stats_dict["sum"] = 300

        reset_stats_dict(stats_dict=stats_dict)
        self.assertEqual(stats_dict["count"], 0)
        self.assertEqual(stats_dict["sum"], 0)

    def test_record_timing_stats_for_function_sample_interval(self):
        stats_dict = get_empty_stats_dict()

        @record_timing_stats_for_function_call(stats_dict, 1)
        def mock_timed_function_1():
            return True

        self.assertEqual(stats_dict["count"], 0)
        self.assertTrue(mock_timed_function_1())
        self.assertEqual(stats_dict["count"], 1)

        stats_dict = get_empty_stats_dict()

        @record_timing_stats_for_function_call(stats_dict, 0.1)
        def mock_timed_function_2():
            return True

        self.assertEqual(stats_dict["count"], 0)
        for _ in range(0, 1000):
            self.assertTrue(mock_timed_function_2())
        self.assertTrue(stats_dict["count"] >= 2)

    @mock.patch("scalyr_agent.timing.timer")
    @mock.patch("scalyr_agent.timing.STATS_DICT_SAMPLE_COUNT_RESET_INTERVAL", 6)
    def test_record_timing_stats_for_function_timing_stats(self, mock_timer):
        mock_timer.side_effect = [0, 10, 10, 15, 20, 32, 30, 40, 40, 50, 0, 0]
        stats_dict = get_empty_stats_dict()

        @record_timing_stats_for_function_call(stats_dict, 1)
        def mock_timed_function():
            return True

        self.assertEqual(stats_dict["count"], 0)
        self.assertTrue(mock_timed_function())
        self.assertEqual(stats_dict["min"], 10 * 1000)
        self.assertEqual(stats_dict["max"], 10 * 1000)
        self.assertEqual(stats_dict["sum"], 10 * 1000)
        self.assertEqual(stats_dict["count"], 1)

        for index in range(0, 4):
            self.assertTrue(mock_timed_function())

        self.assertEqual(stats_dict["min"], 5 * 1000)
        self.assertEqual(stats_dict["max"], 12 * 1000)
        self.assertEqual(stats_dict["sum"], (10 + 5 + 12 + 10 + 10) * 1000)
        self.assertEqual(stats_dict["count"], 5)

        # Stats should be reset
        self.assertTrue(mock_timed_function())
        self.assertEqual(stats_dict["count"], 0)
