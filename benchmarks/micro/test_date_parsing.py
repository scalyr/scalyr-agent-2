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

from scalyr_agent.util import rfc3339_to_nanoseconds_since_epoch
from scalyr_agent.util import rfc3339_to_datetime

DATE_STR = u"2015-08-03T09:12:43.143757463Z"
EXPECTED_RESULT_TIMESTAMP = 1438593163143757463
EXPECTED_RESULT_DT = datetime.datetime(2015, 8, 3, 9, 12, 43, 143757)


def test_rfc3339_to_nanoseconds_since_epoch_with_strptime(benchmark):
    def run_benchmark():
        result = rfc3339_to_nanoseconds_since_epoch(DATE_STR, True)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=1000, rounds=100)
    assert bool(result)
    assert result == EXPECTED_RESULT_TIMESTAMP


def test_rfc3339_to_nanoseconds_since_epoch_without_strptime(benchmark):
    def run_benchmark():
        result = rfc3339_to_nanoseconds_since_epoch(DATE_STR, False)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=1000, rounds=100)
    assert bool(result)
    assert result == EXPECTED_RESULT_TIMESTAMP

    # Verify roundtrip is the same
    result_with_strptime = rfc3339_to_nanoseconds_since_epoch(DATE_STR, True)
    assert result == result_with_strptime


def test_rfc3339_to_datetime_with_strptime(benchmark):
    def run_benchmark():
        result = rfc3339_to_datetime(DATE_STR, True)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=1000, rounds=100)
    assert bool(result)
    assert result == EXPECTED_RESULT_DT


def test_rfc3339_to_datetime_without_strptime(benchmark):
    def run_benchmark():
        result = rfc3339_to_datetime(DATE_STR, False)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=1000, rounds=100)
    assert bool(result)
    assert result == EXPECTED_RESULT_DT

    # Verify roundtrip is the same
    result_with_strptime = rfc3339_to_datetime(DATE_STR, True)
    assert result == result_with_strptime
