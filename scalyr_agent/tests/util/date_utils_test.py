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

import scalyr_agent.util as scalyr_util
from scalyr_agent import date_parsing_utils
from scalyr_agent.test_base import ScalyrTestCase

if six.PY3:
    reload = importlib.reload


class DateUtilsTestCase(ScalyrTestCase):
    def tearDown(self):
        super(DateUtilsTestCase, self).tearDown()

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
        actual = scalyr_util.rfc3339_to_datetime(s)

        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56Z"
        actual = scalyr_util.rfc3339_to_datetime(s)

        self.assertEquals(datetime.datetime(2015, 8, 6, 14, 40, 56), actual)

        s = "2015-08-06T14:40:56.123456"
        actual = scalyr_util.rfc3339_to_datetime(s)
        self.assertEquals(datetime.datetime(2015, 8, 6, 14, 40, 56), actual)

    def test_rfc3339_to_datetime_with_and_without_strptime(self):
        # Verify corectness between two different implementations of this function
        input_strs = [
            "2015-08-06T14:40:56.123456Z",
            "2015-08-06T14:40:56Z",
            "2015-08-06T14:40:56.123456",
        ]
        expected_dts = [
            datetime.datetime(2015, 8, 6, 14, 40, 56, 123456),
            datetime.datetime(2015, 8, 6, 14, 40, 56),
            datetime.datetime(2015, 8, 6, 14, 40, 56),
        ]

        for input_str, expected_dt in zip(input_strs, expected_dts):
            result_with_strptime = date_parsing_utils._rfc3339_to_datetime_strptime(
                input_str
            )
            result_without_strptime = scalyr_util.rfc3339_to_datetime(input_str)

            self.assertEqual(result_with_strptime, expected_dt)
            self.assertEqual(result_with_strptime, result_without_strptime)

    def test_rfc3339_to_datetime_truncated_nano(self):
        s = "2015-08-06T14:40:56.123456789Z"
        expected = datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
        actual = scalyr_util.rfc3339_to_datetime(s)

        self.assertEquals(expected, actual)

    def test_rfc3339_to_datetime_bad_format_date_and_time_separator(self):
        s = "2015-08-06 14:40:56.123456789Z"
        expected = None
        actual = scalyr_util.rfc3339_to_datetime(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_datetime_bad_format_has_timezone(self):
        # currently this function only handles UTC.  Remove this test if
        # updated to be more flexible
        s = "2015-08-06T14:40:56.123456789+04:00"
        expected = None
        actual = scalyr_util.rfc3339_to_datetime(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch(self):
        s = "2015-08-06T14:40:56.123456Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123456)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56.123456"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_with_and_without_strptime(self):
        # Verify corectness between two different implementations of this function
        input_strs = [
            "2015-08-06T14:40:56.123456Z",
            "2015-08-06T14:40:56Z",
            "2015-08-06T14:40:56.123456789Z",
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
        ]

        for input_str, expected_ts in zip(input_strs, expected_tss):
            result_with_strptime = date_parsing_utils._rfc3339_to_nanoseconds_since_epoch_strptime(
                input_str
            )
            result_without_strptime = scalyr_util.rfc3339_to_nanoseconds_since_epoch(
                input_str
            )

            self.assertEqual(result_with_strptime, expected_ts)
            self.assertEqual(result_with_strptime, result_without_strptime)

    def test_rfc3339_to_nanoseconds_since_epoch_no_fractions(self):
        s = "2015-08-06T14:40:56"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

        s = "2015-08-06T14:40:56Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_some_fractions(self):
        s = "2015-08-06T14:40:56.123Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2015, 8, 6, 14, 40, 56, 123000)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
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
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
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
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_strange_value(self):
        s = "2017-09-20T20:44:00.123456Z"
        expected = (
            scalyr_util.microseconds_since_epoch(
                datetime.datetime(2017, 9, 20, 20, 44, 00, 123456)
            )
            * 1000
        )
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertEquals(expected, actual)

    def test_rfc3339_to_nanoseconds_since_epoch_bad_format_has_timezone(self):
        s = "2015-08-06T14:40:56.123456789+04:00"
        actual = scalyr_util.rfc3339_to_nanoseconds_since_epoch(s)
        self.assertIs(None, actual)

    def _delete_modules_from_sys_modules(self, module_names):
        for module_name in module_names:
            if module_name in sys.modules:
                del sys.modules[module_name]
