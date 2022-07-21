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

import random

from functools import wraps
from timeit import default_timer as timer

from scalyr_agent.instrumentation.timing import reset_stats_dict
from scalyr_agent.scalyr_logging import getLogger

__all__ = [
    "time_function_call",
]

LOG = getLogger(__name__)

# After how many samples we should reset the stats dict. This is done to avoid unncessary growing
# of the values in the stats dict and prevent potential overflows
STATS_DICT_SAMPLE_COUNT_RESET_INTERVAL = 10000


def should_sample(sample_rate):
    # type: (float) -> bool
    return random.random() < sample_rate


# TODO: Eventually add dependency on numpy or similar and utilize running / moving mean + percentiles
def time_function_call(stats_dict, sample_rate):
    """
    Utility decorator which records function timing related information (how long the function
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
            stats_dict["count"] += 1
            stats_dict["sum"] += duration_ms
            stats_dict["avg"] = stats_dict["sum"] / stats_dict["count"]

            if duration_ms < stats_dict["min"]:
                stats_dict["min"] = duration_ms
            if duration_ms > stats_dict["max"]:
                stats_dict["max"] = duration_ms

            if stats_dict["count"] >= STATS_DICT_SAMPLE_COUNT_RESET_INTERVAL:
                LOG.debug(
                    "Resetting stats dict %s after %s samples",
                    stats_dict,
                    STATS_DICT_SAMPLE_COUNT_RESET_INTERVAL,
                )
                reset_stats_dict(stats_dict)

            return result

        return wrapper

    return decorate
