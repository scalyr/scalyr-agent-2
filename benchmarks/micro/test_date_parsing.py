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

"""
Benchmarks which measure performance of date parsing functions.
"""

from __future__ import absolute_import

import datetime

import pytest

from scalyr_agent.date_parsing_utils import (
    _rfc3339_to_nanoseconds_since_epoch_string_split,
)
from scalyr_agent.date_parsing_utils import (
    _rfc3339_to_nanoseconds_since_epoch_udatetime,
)

from scalyr_agent.date_parsing_utils import _rfc3339_to_datetime_string_split
from scalyr_agent.date_parsing_utils import _rfc3339_to_datetime_udatetime

from .time_utils import process_time

DATE_WITH_FRACTION_STR = u"2015-08-03T09:12:43.123456"
EXPECTED_RESULT_WITH_FRACTION_TIMESTAMP = 1438593163123456000
EXPECTED_RESULT_WITH_FRACTION_DT = datetime.datetime(2015, 8, 3, 9, 12, 43, 123456)

DATE_WITH_FRACTION_AND_TZ_STR = u"2015-08-03T09:12:43.123456-08:00"
EXPECTED_RESULT_WITH_FRACTION_AND_TZ_TIMESTAMP = 1438621963123456000
EXPECTED_RESULT_WITH_FRACTION_AND_TZ_DT = datetime.datetime(2015, 8, 3, 17, 12, 43, 123456)

DATE_WITHOUT_FRACTION_STR = u"2015-08-03T09:12:43"
EXPECTED_RESULT_WITHOUT_FRACTION_TIMESTAMP = 1438593163000000000
EXPECTED_RESULT_WITHOUT_FRACTION_DT = datetime.datetime(2015, 8, 3, 9, 12, 43)

DATE_WITHOUT_FRACTION_WITH_TZ_STR = u"2015-08-03T09:12:43-08:00"
EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_TIMESTAMP = 1438621963000000000
EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_DT = datetime.datetime(2015, 8, 3, 17, 12, 43)

# If time.process_time is available, we use that so we get more accurate and less noisy results
# on Circle CI

timer = process_time


@pytest.mark.parametrize(
    "with_fraction", [True, False], ids=["fraction", "no_fraction"]
)
@pytest.mark.parametrize(
    "with_tz", [True, False], ids=["tz", "no_tz"]
)
@pytest.mark.benchmark(group="rfc3339_to_nanoseconds_since_epoch", timer=timer)
def test_rfc3339_to_nanoseconds_since_epoch_string_split(benchmark, with_fraction, with_tz):
    if with_fraction:
        if with_tz:
            date_str = DATE_WITH_FRACTION_AND_TZ_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_AND_TZ_TIMESTAMP
        else:
            date_str = DATE_WITH_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_TIMESTAMP
    else:
        if with_tz:
            date_str = DATE_WITHOUT_FRACTION_WITH_TZ_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_TIMESTAMP
        else:
            date_str = DATE_WITHOUT_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_TIMESTAMP

    def run_benchmark():
        result = _rfc3339_to_nanoseconds_since_epoch_string_split(date_str)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=200, rounds=200)
    assert bool(result)
    assert result == expected_result


@pytest.mark.parametrize(
    "with_fraction", [True, False], ids=["fraction", "no_fraction"]
)
@pytest.mark.parametrize(
    "with_tz", [True, False], ids=["tz", "no_tz"]
)
@pytest.mark.benchmark(group="rfc3339_to_nanoseconds_since_epoch", timer=timer)
def test_rfc3339_to_nanoseconds_since_epoch_udatetime(benchmark, with_fraction, with_tz):
    if with_fraction:
        if with_tz:
            date_str = DATE_WITH_FRACTION_AND_TZ_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_AND_TZ_TIMESTAMP
        else:
            date_str = DATE_WITH_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_TIMESTAMP
    else:
        if with_tz:
            date_str = DATE_WITHOUT_FRACTION_WITH_TZ_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_TIMESTAMP
        else:
            date_str = DATE_WITHOUT_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_TIMESTAMP

    def run_benchmark():
        result = _rfc3339_to_nanoseconds_since_epoch_udatetime(date_str)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=200, rounds=200)
    assert result == expected_result


@pytest.mark.parametrize(
    "with_fraction", [True, False], ids=["fraction", "no_fraction"]
)
@pytest.mark.parametrize(
    "with_tz", [True, False], ids=["tz", "no_tz"]
)
@pytest.mark.benchmark(group="rfc3339_to_datetime", timer=timer)
def test_rfc3339_to_datetime_string_split(benchmark, with_fraction, with_tz):
    if with_fraction:
        if with_tz:
            date_str = DATE_WITH_FRACTION_AND_TZ_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_AND_TZ_DT
        else:
            date_str = DATE_WITH_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_DT
    else:
        if with_tz:
            date_str = DATE_WITHOUT_FRACTION_WITH_TZ_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_DT
            pass
        else:
            date_str = DATE_WITHOUT_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_DT

    def run_benchmark():
        result = _rfc3339_to_datetime_string_split(date_str)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=200, rounds=200)
    assert result == expected_result


@pytest.mark.parametrize(
    "with_fraction", [True, False], ids=["fraction", "no_fraction"]
)
@pytest.mark.parametrize(
    "with_tz", [True, False], ids=["tz", "no_tz"]
)
@pytest.mark.benchmark(group="rfc3339_to_datetime", timer=timer)
def test_rfc3339_to_datetime_udatetime(benchmark, with_fraction, with_tz):
    if with_fraction:
        if with_tz:
            date_str = DATE_WITH_FRACTION_AND_TZ_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_AND_TZ_DT
        else:
            date_str = DATE_WITH_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITH_FRACTION_DT
    else:
        if with_tz:
            date_str = DATE_WITHOUT_FRACTION_WITH_TZ_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_WITH_TZ_DT
            pass
        else:
            date_str = DATE_WITHOUT_FRACTION_STR
            expected_result = EXPECTED_RESULT_WITHOUT_FRACTION_DT

    def run_benchmark():
        result = _rfc3339_to_datetime_udatetime(date_str)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=200, rounds=200)
    assert result == expected_result
