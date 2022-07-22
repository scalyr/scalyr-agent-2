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

import time

from collections import OrderedDict

import mock

from scalyr_agent.util import get_hash_for_flat_dictionary
from scalyr_agent.metrics.base import get_functions_for_metric
from scalyr_agent.metrics.base import clear_internal_cache
from scalyr_agent.metrics.functions import RateMetricFunction
from scalyr_agent.test_base import ScalyrTestCase

__all__ = [
    "RateMetricFunctionTestCase",
]


class RateMetricFunctionTestCase(ScalyrTestCase):
    def setUp(self):
        super(RateMetricFunctionTestCase, self).setUp()
        clear_internal_cache()

    def tearDown(self):
        super(RateMetricFunctionTestCase, self).tearDown()
        clear_internal_cache()

    def test_get_hash_for_flat_dictionary(self):
        dict1 = {
            "foo": "bar",
            "bar": 1,
            "baz": "none",
            "none": None,
            "a": True,
            "0": 0,
        }
        dict2 = OrderedDict(
            [
                ("0", 0),
                ("bar", 1),
                ("foo", "bar"),
                ("a", True),
                ("baz", "none"),
                ("none", None),
            ]
        )
        dict3 = OrderedDict(
            [
                ("foo", "bar"),
                ("a", True),
                ("bar", 1),
                ("0", 0),
                ("baz", "none"),
                ("none", None),
            ]
        )
        dict4 = OrderedDict(
            [
                ("foo", "bar"),
                ("a", True),
                ("bar", 0),
                ("0", 0),
                ("baz", "none"),
                ("none", None),
            ]
        )

        dict5 = {}
        dict6 = OrderedDict({})
        dict7 = None

        result1 = get_hash_for_flat_dictionary(dict1)
        result2 = get_hash_for_flat_dictionary(dict2)
        result3 = get_hash_for_flat_dictionary(dict3)
        result4 = get_hash_for_flat_dictionary(dict4)
        self.assertEqual(result1, result2)
        self.assertEqual(result3, result3)
        self.assertNotEqual(result3, result4)
        self.assertNotEqual(result1, result4)

        result5 = get_hash_for_flat_dictionary(dict5)
        result6 = get_hash_for_flat_dictionary(dict6)
        result7 = get_hash_for_flat_dictionary(dict7)
        self.assertEqual(result5, result6)
        self.assertEqual(result5, result7)

    def test_rate_metric_function_metric_name_not_in_allowlist(self):
        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 0
        monitor._global_config.instrumentation_stats_log_interval = 10
        monitor._global_config.calculate_rate_metric_names = [
            "openmetrics_monitor:metric1",
            "openmetrics_monitor:metric2",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=user",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel",
        ]

        # Invalid metric name (metric name not in allowlist)
        metric_name = "metric_invalid"
        funcs = get_functions_for_metric(monitor=monitor, metric_name=metric_name)
        self.assertEqual(funcs, [])

    def test_rate_metric_function_metric_name_without_extra_fields(self):
        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 0
        monitor._global_config.instrumentation_stats_log_interval = 10
        monitor._global_config.calculate_rate_metric_names = [
            "openmetrics_monitor:metric1",
            "openmetrics_monitor:metric2",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=user",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel",
        ]

        ts1 = 10
        ts2 = 70
        ts3 = 130
        ts4 = 190

        val1 = 20
        val2 = 30
        val3 = 40
        val4 = 100

        # Valid metric name, no extra_fields
        metric_name = "metric1"
        extra_fields = {}

        funcs = get_functions_for_metric(monitor=monitor, metric_name=metric_name)
        self.assertEqual(len(funcs), 1)
        self.assertTrue(isinstance(funcs[0], RateMetricFunction))

        func = funcs[0]
        func.clear_cache()

        # Initial call, no previous data available yet
        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=val1,
        )
        self.assertIsNone(result)

        # (30 - 20) / (70 - 10)
        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=val2,
        )
        self.assertEqual(result, [("metric1_rate", 0.16667)])

        # (40 - 30) / (130 - 70)
        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts3 * 1000,
            metric_value=val3,
        )
        self.assertEqual(result, [("metric1_rate", 0.16667)])

        # (100 - 40) / (190 - 130)
        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts4 * 1000,
            metric_value=val4,
        )
        self.assertEqual(result, [("metric1_rate", 1.0)])

        # There should be one internal cache entry
        self.assertEqual(len(func.RATE_CALCULATION_METRIC_VALUES), 1)

    def test_rate_metric_function_metric_name_with_extra_fields(self):
        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 0
        monitor._global_config.instrumentation_stats_log_interval = 10
        monitor._global_config.calculate_rate_metric_names = [
            "openmetrics_monitor:metric1",
            "openmetrics_monitor:metric2",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=user",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel",
        ]

        ts1 = 10
        ts2 = 70

        val1 = 20

        # Valid metric name, different extra fields, ensure rates are scoped to particular extra
        # fields
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "user", "pod": "pod1", "node": "node2"}

        funcs = get_functions_for_metric(monitor=monitor, metric_name=metric_name)
        self.assertEqual(len(funcs), 1)
        self.assertTrue(isinstance(funcs[0], RateMetricFunction))

        func = funcs[0]

        # Initial call, no previous data available yet
        # pod=pod1, mode=user, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node1", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=val1,
        )
        self.assertIsNone(result)

        # pod=pod1, mode=user, node=node2
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node2", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=15,
        )
        self.assertIsNone(result)

        # pod=pod1, mode=kernel, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node1", "mode": "kernel"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=99,
        )
        self.assertIsNone(result)

        # pod=pod2, mode=user, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod2", "node": "node1", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=val1,
        )
        self.assertIsNone(result)

        # pod=pod2, mode=kernel, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod2", "node": "node1", "mode": "kernel"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts1 * 1000,
            metric_value=88,
        )
        self.assertIsNone(result)

        # pod=pod1, mode=user, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node1", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=300,
        )
        self.assertEqual(result, [("docker.cpu_usage_seconds_total_rate", 4.66667)])

        # pod=pod1, mode=kernel, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node1", "mode": "kernel"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=100,
        )
        self.assertEqual(result, [("docker.cpu_usage_seconds_total_rate", 0.01667)])

        # pod=pod1, mode=user, node=node2
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod1", "node": "node2", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=20,
        )
        self.assertEqual(result, [("docker.cpu_usage_seconds_total_rate", 0.08333)])

        # pod=pod2, mode=user, node=node1
        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod2", "node": "node1", "mode": "user"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=100,
        )
        self.assertEqual(result, [("docker.cpu_usage_seconds_total_rate", 1.33333)])

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"pod": "pod2", "node": "node1", "mode": "kernel"}

        result = func.calculate(
            monitor=monitor,
            metric_name=metric_name,
            extra_fields=extra_fields,
            timestamp=ts2 * 1000,
            metric_value=92,
        )
        self.assertEqual(result, [("docker.cpu_usage_seconds_total_rate", 0.06667)])

        # There should be 5 entries in the internal value cache:
        # - pod=pod1, node=node1, mode=user
        # - pod=pod1, node=node1, mode=kernel
        # - pod=pod1, node=node2, mode=user
        # - pod=pod2, node=node1, mode=user
        # - pod=pod2, node=node1, mode=kernel
        self.assertEqual(len(func.RATE_CALCULATION_METRIC_VALUES), 5)

    def test_should_calculate_for_monitor_and_metric_function(self):
        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 0
        monitor._global_config.instrumentation_stats_log_interval = 10
        monitor._global_config.calculate_rate_metric_names = [
            "openmetrics_monitor:metric1",
            "openmetrics_monitor:metric2",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=user",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel",
        ]

        func = RateMetricFunction()

        metric_name = "metric"

        result = func.should_calculate_for_monitor_and_metric(
            monitor=monitor, metric_name=metric_name
        )
        self.assertFalse(result)

        metric_name = "metric0"

        result = func.should_calculate_for_monitor_and_metric(
            monitor=monitor, metric_name=metric_name
        )
        self.assertFalse(result)

        metric_name = "metric1"

        result = func.should_calculate_for_monitor_and_metric(
            monitor=monitor, metric_name=metric_name
        )
        self.assertTrue(result)

        metric_name = "docker.cpu_usage_seconds_total"

        result = func.should_calculate_for_monitor_and_metric(
            monitor=monitor, metric_name=metric_name
        )
        self.assertTrue(result)

    def test_should_calculate_function(self):
        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 0
        monitor._global_config.instrumentation_stats_log_interval = 10
        monitor._global_config.calculate_rate_metric_names = [
            "openmetrics_monitor:metric1",
            "openmetrics_monitor:metric2",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=user",
            "openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel",
        ]

        func = RateMetricFunction()

        metric_name = "metric"
        extra_fields = {}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertFalse(result)

        metric_name = "metric0"
        extra_fields = {}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertFalse(result)

        metric_name = "metric1"
        extra_fields = {}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "metric1"
        extra_fields = {"foo": "bar"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "metric1"
        extra_fields = {"bar": "baz"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "metric2"
        extra_fields = {}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertFalse(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"foo": "bar"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertFalse(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "total"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertFalse(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "user"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "user", "foo": "bar"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "kernel"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

        metric_name = "docker.cpu_usage_seconds_total"
        extra_fields = {"mode": "kernel", "bar": "baz"}

        result = func.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        )
        self.assertTrue(result)

    def test_old_entries_cleanup(self):
        now_ts = int(time.time())

        monitor = mock.Mock()
        monitor.monitor_module_name = "openmetrics_monitor"
        monitor.short_hash = "hashhash"
        monitor.get_calculate_rate_metric_names.return_value = []
        monitor._global_config = mock.Mock()
        monitor._global_config.metric_functions_cleanup_interval = 60
        monitor._global_config.instrumentation_stats_log_interval = 10

        func = RateMetricFunction()
        RateMetricFunction.DELETE_OLD_VALUES_THRESHOLD_SECONDS = 60
        RateMetricFunction.RATE_CALCULATION_METRIC_VALUES = {
            "one": (now_ts, 1),
            "two": (now_ts - 10, 1),
            "three": (now_ts - 50, 1),
            "four": (now_ts - 70, 1),
            "five": (now_ts - 80, 1),
            "six": (now_ts - 90, 1),
        }

        self.assertEqual(len(func.RATE_CALCULATION_METRIC_VALUES), 6)
        func._remove_old_entries(monitor=monitor)
        self.assertEqual(RateMetricFunction.LAST_CLEANUP_RUNTIME_TS, now_ts)
        self.assertEqual(len(func.RATE_CALCULATION_METRIC_VALUES), 3)
        self.assertTrue("one" in func.RATE_CALCULATION_METRIC_VALUES)
        self.assertTrue("two" in func.RATE_CALCULATION_METRIC_VALUES)
        self.assertTrue("three" in func.RATE_CALCULATION_METRIC_VALUES)
