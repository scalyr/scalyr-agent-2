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
# ------------------------------------------------------------------------

"""
Metric functions related base functionality.

NOTE: Right now this code is only used inside a single thread so it's not designed to be thread
safe.
"""

__all__ = [
    "get_functions_for_metric",
    "clear_internal_cache",
]

if False:
    from typing import List

    from scalyr_agent.scalyr_monitor import ScalyrMonitor  # NOQA

import six

from repoze.lru import LRUCache  # pylint: disable=import-error

from scalyr_agent.util import get_flat_dictionary_memory_usage
from scalyr_agent.instrumentation.timing import get_empty_stats_dict
from scalyr_agent.instrumentation.decorators import time_function_call
from scalyr_agent.metrics.functions import MetricFunction
from scalyr_agent.metrics.functions import RateMetricFunction
from scalyr_agent.scalyr_logging import getLogger
from scalyr_agent.scalyr_logging import LazyOnPrintEvaluatedFunction

LOG = getLogger(__name__)


# Stores a list of class instance (singleton) for each available metric function.
# TODO: Once we only support Python 3 use registry / adapter pattern.
FUNCTIONS_REGISTRY = {
    "rate": RateMetricFunction(),
}

# Maximum cache size for MONITOR_METRIC_TO_FUNCTIONS_CACHE LRU cache. Instrumentation shows that
# ~500 entries use around 0.1 MB of memory so 20.000 would mean about 4 MB of memory + overhead
# (let's say 8 MB to be on the safe side)
MAX_CACHE_SIZE = 20000

# Stores cached list of MetricFunction class instances for the provided monitor and metric name.
# This cache needs to be invalidated each time config is reloaded and config change is detected.
MONITOR_METRIC_TO_FUNCTIONS_CACHE = LRUCache(MAX_CACHE_SIZE)

# Dictionary which stores timing / run time information for "get_functions_for_metric" function
GET_FUNCTIONS_FOR_METRICS_RUNTIME_STATS = get_empty_stats_dict()


# References to objects which are evaluated lazily when __str__() method (aka print or %s format)
# is called on a specific value. Meant to be used with scalyr_logging.log() with
# "limit_once_per_x_secs" argument so the values are only evaluated when we don't hit rate limit and
# when log message is actually printed.
LAZY_PRINT_CACHE_SIZE_LENGTH = LazyOnPrintEvaluatedFunction(
    lambda: len(MONITOR_METRIC_TO_FUNCTIONS_CACHE.data)
)
LAZY_PRINT_CACHE_SIZE_BYTES = LazyOnPrintEvaluatedFunction(
    lambda: get_flat_dictionary_memory_usage(MONITOR_METRIC_TO_FUNCTIONS_CACHE.data)
)

LAZY_PRINT_CACHE_HITS = LazyOnPrintEvaluatedFunction(
    lambda: MONITOR_METRIC_TO_FUNCTIONS_CACHE.hits
)
LAZY_PRINT_CACHE_MISSES = LazyOnPrintEvaluatedFunction(
    lambda: MONITOR_METRIC_TO_FUNCTIONS_CACHE.misses
)
LAZY_PRINT_CACHE_LOOKUPS = LazyOnPrintEvaluatedFunction(
    lambda: MONITOR_METRIC_TO_FUNCTIONS_CACHE.lookups
)
LAZY_PRINT_CACHE_EVICTIONS = LazyOnPrintEvaluatedFunction(
    lambda: MONITOR_METRIC_TO_FUNCTIONS_CACHE.evictions
)

LAZY_PRINT_TIMING_MIN = LazyOnPrintEvaluatedFunction(
    lambda: round(GET_FUNCTIONS_FOR_METRICS_RUNTIME_STATS["min"], 4)
)
LAZY_PRINT_TIMING_MAX = LazyOnPrintEvaluatedFunction(
    lambda: round(GET_FUNCTIONS_FOR_METRICS_RUNTIME_STATS["max"], 4)
)
LAZY_PRINT_TIMING_AVG = LazyOnPrintEvaluatedFunction(
    lambda: round(GET_FUNCTIONS_FOR_METRICS_RUNTIME_STATS["avg"], 4)
)


@time_function_call(GET_FUNCTIONS_FOR_METRICS_RUNTIME_STATS, 0.001)
def get_functions_for_metric(monitor, metric_name):
    # type: (ScalyrMonitor, six.text_type) -> List[MetricFunction]
    """
    Return a list of class instances for functions which should be applied to this metric.

    TODO:
      - [ ] To speed up the common case then there are no functions defined, we should short circuit
           in such scenario.
    """
    cache_key = "%s:%s" % (monitor.short_hash, metric_name)

    # TODO: Use LRU cache with limited max size

    # NOTE: Since there can be tons of different unique extra_fields values for a specific metric
    # and as such permutations, we have first level cache for monitor and metric name here. Having
    # cache entry for each possible monitor name, metric name, extra_fields values would result in
    # a cache which can grow too large. And we do still want some kind of cache since having no
    # cache would result in running this "should_calculate()" logic for every single emitted metric
    # which is expensive.
    if MONITOR_METRIC_TO_FUNCTIONS_CACHE.get(cache_key) is None:
        result = []

        for function_instance in FUNCTIONS_REGISTRY.values():
            if function_instance.should_calculate_for_monitor_and_metric(
                monitor=monitor,
                metric_name=metric_name,
            ):
                result.append(function_instance)

        MONITOR_METRIC_TO_FUNCTIONS_CACHE.put(cache_key, result)

    # Periodically print cache size and function timing information
    # NOTE: We don't have direct access to global config here so we access it via monitor. An
    # alternative would be to use a module level variable which is updated during config load and
    # re-load process (as initially implemented in https://github.com/scalyr/scalyr-agent-2/pull/942)
    log_interval = (
        monitor._global_config
        and monitor._global_config.instrumentation_stats_log_interval
        or 0
    )
    if log_interval > 0:
        LOG.info(
            "agent_instrumentation_stats key=monitor_metric_to_function_cache_stats "
            "cache_entries=%s cache_size_bytes=%s cache_hits=%s cache_misses=%s cache_lookups=%s cache_evictions=%s",
            LAZY_PRINT_CACHE_SIZE_LENGTH,
            LAZY_PRINT_CACHE_SIZE_BYTES,
            LAZY_PRINT_CACHE_HITS,
            LAZY_PRINT_CACHE_MISSES,
            LAZY_PRINT_CACHE_LOOKUPS,
            LAZY_PRINT_CACHE_EVICTIONS,
            limit_key="mon-met-cache-stats",
            limit_once_per_x_secs=log_interval,
        )
        LOG.info(
            "agent_instrumentation_stats key=agent_get_function_for_metric_timing_stats avg=%s min=%s max=%s",
            LAZY_PRINT_TIMING_AVG,
            LAZY_PRINT_TIMING_MIN,
            LAZY_PRINT_TIMING_MAX,
            limit_key="mon-met-timing-stats",
            limit_once_per_x_secs=log_interval,
        )

    return MONITOR_METRIC_TO_FUNCTIONS_CACHE.get(cache_key)


def clear_registry_cache():
    global MONITOR_METRIC_TO_FUNCTIONS_CACHE

    LOG.debug("Clearing registry cache")

    MONITOR_METRIC_TO_FUNCTIONS_CACHE.clear()


def clear_internal_cache():
    """
    Clear internal cache where we store various metadata and metric related values which are needed
    to calculate derived metrics.
    """
    LOG.debug("Clearing internal cache")

    # 1. Clear module level cache (registry)
    clear_registry_cache()

    # 2. Clear function level cache
    for function_instance in FUNCTIONS_REGISTRY.values():
        function_instance.clear_cache()
