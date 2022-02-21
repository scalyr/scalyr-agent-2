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

import sys
import datetime

import importlib

import mock
import six
from six.moves import zip

from scalyr_agent import date_parsing_utils
import scalyr_agent.util as scalyr_util
from scalyr_agent.test_base import ScalyrTestCase

from scalyr_agent.test_base import skipIf

if six.PY3:
    reload = importlib.reload
try:
    import udatetime
except ImportError:
    udatetime = None


class DateUtilsTestCase(ScalyrTestCase):
    def tearDown(self):
        super(DateUtilsTestCase, self).tearDown()

    @skipIf(not udatetime, "udatetime not available, skipping test")
    def test_rfc3339_to_datetime_with_timezone_udatetime(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-00:00"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-08:00"
        expected = datetime.datetime(2015, 8, 6, 22, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-02:00"
        expected = datetime.datetime(2015, 8, 6, 16, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+02:00"
        expected = datetime.datetime(2015, 8, 6, 12, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+08:00"
        expected = datetime.datetime(2015, 8, 6, 6, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_udatetime(s)

        self.assertEquals(expected, actual)

    def test_rfc3339_to_datetime_with_timezone_string_split(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-00:00"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-08:00"
        expected = datetime.datetime(2015, 8, 6, 22, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-02:00"
        expected = datetime.datetime(2015, 8, 6, 16, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+02:00"
        expected = datetime.datetime(2015, 8, 6, 12, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+08:00"
        expected = datetime.datetime(2015, 8, 6, 6, 40, 56, 123456)
        actual = date_parsing_utils._rfc3339_to_datetime_string_split(s)

        self.assertEquals(expected, actual)

    @skipIf(not udatetime, "udatetime not available, skipping test")
    def test_rfc3339_to_nanoseconds_since_epoch_with_timezone_udatetime(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = 1438872056123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-00:00"
        expected = 1438872056123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-08:00"
        expected = 1438900856123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-02:00"
        expected = 1438879256123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+02:00"
        expected = 1438864856123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+08:00"
        expected = 1438843256123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(s)

        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_with_timezone_string_split(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = 1438872056123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-00:00"
        expected = 1438872056123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-08:00"
        expected = 1438900856123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456-02:00"
        expected = 1438879256123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+02:00"
        expected = 1438864856123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456+08:00"
        expected = 1438843256123456000
        actual = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(s)

        self.assertEquals(expected, actual)

    def test_verify_correct_default_rfc3339_to_implementation_is_used(self):
        # 1. udatetime is available, we should use that
        sys.modules["udatetime"] = mock.Mock()

        import scalyr_agent.date_parsing_utils

        reload(scalyr_agent.date_parsing_utils)

        self.assertTrue(
            "udatetime"
            in scalyr_agent.date_parsing_utils.rfc3339_to_nanoseconds_since_epoch.__name__
        )
        self.assertTrue(
            "udatetime" in scalyr_agent.date_parsing_utils.rfc3339_to_datetime.__name__
        )

        # 2. udatetime is not available, we should fall back to string split implementation
        self._delete_modules_from_sys_modules(
            ["udatetime", "udatetime.rfc3339", "scalyr_agent.date_parsing_utils"]
        )
        sys.modules["udatetime"] = ""

        import scalyr_agent.date_parsing_utils

        reload(scalyr_agent.date_parsing_utils)

        self.assertTrue(
            "string_split"
            in scalyr_agent.date_parsing_utils.rfc3339_to_nanoseconds_since_epoch.__name__
        )
        self.assertTrue(
            "string_split"
            in scalyr_agent.date_parsing_utils.rfc3339_to_datetime.__name__
        )

    def test_rfc3339_to_datetime(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils.rfc3339_to_datetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56Z"
        actual = date_parsing_utils.rfc3339_to_datetime(s)

        self.assertEquals(datetime.datetime(2015, 8, 6, 14, 40, 56), actual)

        s = "2015-08-06T14:40:56.123456"
        actual = date_parsing_utils.rfc3339_to_datetime(s)
        self.assertEquals(datetime.datetime(2015, 8, 6, 14, 40, 56, 123456), actual)

    @skipIf(not udatetime, "udatetime not available, skipping test")
    def test_rfc3339_to_datetime_string_split_and_udatetime(self):
        # Verify corectness between two different implementations of this function
        input_strs = [
            "2015-08-06T14:40:56.123456Z",
            "2015-08-06T14:40:56Z",
            "2015-08-06T14:40:56.123456",
            "2022-01-31T10:52:30.148000269-08:00",
        ]
        expected_dts = [
            datetime.datetime(2015, 8, 6, 14, 40, 56, 123456),
            datetime.datetime(2015, 8, 6, 14, 40, 56),
            datetime.datetime(2015, 8, 6, 14, 40, 56, 123456),
            datetime.datetime(2022, 1, 31, 18, 52, 30, 148000),
        ]

        for input_str, expected_dt in zip(input_strs, expected_dts):
            result_udatetime = date_parsing_utils._rfc3339_to_datetime_udatetime(
                input_str
            )
            result_string_split = date_parsing_utils.rfc3339_to_datetime(input_str)

            self.assertEqual(result_udatetime, expected_dt)
            self.assertEqual(result_string_split, expected_dt)
            self.assertEqual(result_udatetime, result_string_split)

    def test_rfc3339_to_datetime_truncated_nano(self):
        s = "2015-08-06T14:40:56.123456789Z"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = date_parsing_utils.rfc3339_to_datetime(s)

        self.assertEquals(expected, actual)

    def test_rfc3339_to_datetime_bad_format_date_and_time_separator(self):
        s = "2015-08-06 14:40:56.123456789Z"
        expected = None
        actual = date_parsing_utils.rfc3339_to_datetime(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    @skipIf(not udatetime, "udatetime not available, skipping test")
    def test_rfc3339_to_nanoseconds_since_epoch_string_split_and_udatetime(
        self,
    ):
        # Verify corectness between two different implementations of this function
        input_strs = [
            "2015-08-06T14:40:56.123456Z",
            "2015-08-06T14:40:56Z",
            "2015-08-06T14:40:56.123456789Z",
            "2022-01-31T10:52:30.148000269-08:00",
        ]

        expected_tss = [
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000,
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000,
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
            + 789,
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2022, 1, 31, 18, 52, 30, 148000),
            )
            * 1000
            + 269,
        ]

        for input_str, expected_ts in zip(input_strs, expected_tss):
            result_udatetime = (
                date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_udatetime(
                    input_str
                )
            )
            result_string_split = (
                date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_string_split(
                    input_str
                )
            )

            self.assertEqual(result_udatetime, expected_ts)
            self.assertEqual(result_string_split, expected_ts)
            self.assertEqual(result_udatetime, result_string_split)

    def test_rfc3339_to_nanoseconds_since_epoch_no_fractions(self):
        s = "2015-08-06T14:40:56"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_some_fractions(self):
        s = "2015-08-06T14:40:56.123Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123000)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_many_fractions(self):
        s = "2015-08-06T14:40:56.123456789Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
            + 789
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_too_many_fractions(self):
        s = "2015-08-06T14:40:56.123456789999Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
            + 789
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_strange_value(self):
        s = "2017-09-20T20:44:00.123456Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2017, 9, 20, 20, 44, 00, 123456)
            )
            * 1000
        )
        actual = date_parsing_utils.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_get_fractional_nanos(self):
        value = "2015-08-06T14:40:56.123456789999Z"
        actual = date_parsing_utils._get_fractional_nanos(value)
        expected = 123456789
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.12"
        actual = date_parsing_utils._get_fractional_nanos(value)
        expected = 12 * 1000 * 10000
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56"
        actual = date_parsing_utils._get_fractional_nanos(value)
        expected = 0
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.9999"
        actual = date_parsing_utils._get_fractional_nanos(value)
        expected = 9999 * 1000 * 100
        self.assertEqual(actual, expected)

    def test_add_fractional_part_to_dt(self):
        value = "2015-08-06T14:40:56.123456789999Z"
        parts = value.split(".")
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56)
        actual = date_parsing_utils._add_fractional_part_to_dt(dt=dt, parts=parts)
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.12"
        parts = value.split(".")
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56)
        actual = date_parsing_utils._add_fractional_part_to_dt(dt=dt, parts=parts)
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 12 * 1000 * 10)
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56"
        parts = value.split(".")
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56)
        actual = date_parsing_utils._add_fractional_part_to_dt(dt=dt, parts=parts)
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 0)
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.9999"
        parts = value.split(".")
        dt = datetime.datetime(2015, 8, 6, 14, 40, 56)
        actual = date_parsing_utils._add_fractional_part_to_dt(dt=dt, parts=parts)
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 999900)
        self.assertEqual(actual, expected)

    def test_get_udatetime_safe_string(self):
        value = "2015-08-06T14:40:56"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56"
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56Z"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56Z"
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.1234"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56.1234"
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.123456Z"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56"
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.123456-08:00"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56-08:00"
        self.assertEqual(actual, expected)

        value = "2015-08-06T14:40:56.123456789+06:00"
        actual = date_parsing_utils._get_udatetime_safe_string(value)
        expected = "2015-08-06T14:40:56+06:00"
        self.assertEqual(actual, expected)

    def _delete_modules_from_sys_modules(self, module_names):
        for module_name in module_names:
            if module_name in sys.modules:
                del sys.modules[module_name]
