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

__all__ = [
    "get_instrumentation_log_interval",
    "update_instrumentation_log_interval",
]

# How often (in seconds) to log various internal cache related statistics
# Defaults to 0 aka logging is disabled. In production this value should be set to value > 10
# minutes to avoid overhead
INSTRUMENTATION_STATS_LOG_INTERVAL_SECONDS = 0


def get_instrumentation_log_interval():
    # type: () -> int
    return INSTRUMENTATION_STATS_LOG_INTERVAL_SECONDS


def update_instrumentation_log_interval(interval):
    # type: (int) -> None
    """
    Update the value of CACHE_STATS_LOG_INTERVAL_SECONDS variable.
    """
    global INSTRUMENTATION_STATS_LOG_INTERVAL_SECONDS
    INSTRUMENTATION_STATS_LOG_INTERVAL_SECONDS = interval
