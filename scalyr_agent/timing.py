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

"""
This module contains various utility code and functions for recording various code run time and
timing based information.
"""

if False:
    from typing import Dict

import random

from functools import wraps
from timeit import default_timer as timer

__all__ = [
    "get_empty_stats_dict",
    "reset_stats_dict",
    "record_timing_stats_for_function_call",
]


def should_sample(sample_rate):
    return random.random() < sample_rate


def get_empty_stats_dict():
    # type: () -> Dict[str, float]
    return reset_stats_dict({})


def reset_stats_dict(stats_dict):
    # type: Dict[str, float] -> None
    """
    Reset values for the provided function run time stats dictionary.
    """
    stats_dict["min"] = float("inf")
    stats_dict["max"] = float("-inf")
    stats_dict["avg"] = 0.0
    stats_dict["sum"] = 0.0
    stats_dict["count"] = 0.0
    return stats_dict


# TODO: Eventually add dependency on numpy or similar and utilize running / moving mean + percentiles
def record_timing_stats_for_function_call(stats_obj, sample_rate):
    """
    Utility decorator which records records function timing related information (how long the function
    took to complete in milliseconds) into the provided stats dictionary.

    The following values are tracked / record:

        - min run time
        - max run time
        - average run time

    To avoid overhead of timing every single function call, it uses random sampling with the provided
    sample rate. To avoid overhead, sampling rate of 1 in 1000 or higher is recommended (0.001) for
    functions which are called relatively frequently.
    """

    def decorate(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not should_sample(sample_rate):
                # No stats recording should be done
                return func(*args, **kwargs)

            start_ts = timer()
            result = func(*args, **kwargs)
            end_ts = timer()

            duration_ms = (end_ts - start_ts) * 1000

            # To avoid values from growing very large and potentially overflowing (for very slow
            # functions), we periodically reset the stats. Keep in mind that this is not ideal and
            # using moving / running values with a particular window size would be better, but that
            # would require us to add a dependency on numpy or a similar library.
            stats_obj["count"] += 1
            stats_obj["sum"] += duration_ms
            stats_obj["avg"] = stats_obj["sum"] / stats_obj["count"]

            if duration_ms < stats_obj["min"]:
                stats_obj["min"] = duration_ms
            if duration_ms > stats_obj["max"]:
                stats_obj["max"] = duration_ms

            if stats_obj["count"] >= 10000:
                reset_stats_dict(stats_obj)

            return result

        return wrapper

    return decorate
