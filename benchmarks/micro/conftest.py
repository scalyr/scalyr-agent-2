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

import pytest

from scalyr_agent import compat

# A list of custom metrics which should be included in the generated pytest benchmark result JSON
# file
CUSTOM_METRICS = [
    "compression_ratio",
]

# If set, we will force all the pytest benchmark units to the provided values.
# This comes handy when submitting data to CodeSpeed where we want to use the same and consistent
# units across multiple runs.
# By default, pytest benchmark will automatically adjust units based on the actual test results.
# This may result in different units across different benchmarks and runs.
PYTEST_BENCH_FORCE_UNIT = compat.os_environ_unicode.get("PYTEST_BENCH_FORCE_UNIT", None)

if PYTEST_BENCH_FORCE_UNIT:
    if PYTEST_BENCH_FORCE_UNIT == "s":
        UNIT_SCALE = 1
        UNIT_PREFIX = ""
    elif PYTEST_BENCH_FORCE_UNIT == "ms":
        UNIT_SCALE = 1000
        UNIT_PREFIX = "m"
    elif PYTEST_BENCH_FORCE_UNIT == "us":
        UNIT_SCALE = 1000000
        UNIT_PREFIX = "u"
    elif PYTEST_BENCH_FORCE_UNIT == "ns":
        UNIT_SCALE = 1000000000
        UNIT_PREFIX = "n"
    else:
        raise ValueError("Invalid unit: %s" % (PYTEST_BENCH_FORCE_UNIT))

if PYTEST_BENCH_FORCE_UNIT:

    def pytest_benchmark_scale_unit(config, unit, benchmarks, best, worst, sort):
        """
        Custom scale function to ensure we use consistent units for all the micro benchmarks.

        We convert timing data to milliseconds and "throughput" / operations data to 1000s
        of operations per second.
        """
        if unit == "seconds":
            prefix = UNIT_PREFIX
            scale = UNIT_SCALE
        elif unit == "operations":
            prefix = "K"
            scale = 0.001
        else:
            raise RuntimeError("Unexpected measurement unit %r" % unit)

        return prefix, scale


@pytest.mark.hookwrapper
def pytest_benchmark_generate_json(
    config, benchmarks, include_data, machine_info, commit_info
):
    """
    Hook which makes sure we include custom metrics such as compression_ratio in the output JSON.
    """
    for benchmark in benchmarks:
        for metric_name in CUSTOM_METRICS:
            metric_value = getattr(benchmark.stats, "compression_ratio", None)

            if metric_value is None:
                continue

            benchmark.stats.fields = list(benchmark.stats.fields)
            benchmark.stats.fields += [metric_name]

    yield
