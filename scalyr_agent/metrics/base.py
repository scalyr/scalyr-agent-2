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
    from typing import Dict

    from scalyr_agent.scalyr_monitor import ScalyrMonitor  # NOQA

import six

from scalyr_agent.metrics.functions import MetricFunction
from scalyr_agent.metrics.functions import RateMetricFunction
from scalyr_agent.scalyr_logging import getLogger

LOG = getLogger(__name__)


# Stores a list of class instance (singleton) for each available metric function.
# TODO: Once we only support Python 3 use registry / adapter pattern.
FUNCTIONS_REGISTRY = {
    "rate": RateMetricFunction(),
}

# Stores cached list of MetricFunction class instances for the provided monitor and metric name.
# This cache needs to be invalidated each time config is reloaded and config change is detected.
MONITOR_METRIC_TO_FUNCTIONS_CACHE = (
    {}
)  # type: Dict[six.text_type, List[MetricFunction]]


def get_functions_for_metric(monitor, metric_name):
    # type: (ScalyrMonitor, six.text_type) -> List[MetricFunction]
    """
    Return a list of class instances for functions which should be applied to this metric.

    TODO:
      - [ ] To speed up the common case then there are no functions defined, we should short circuit
           in such scenario.
    """
    cache_key = "%s.%s" % (monitor.short_hash, metric_name)

    if cache_key not in MONITOR_METRIC_TO_FUNCTIONS_CACHE:
        result = []

        for function_instance in FUNCTIONS_REGISTRY.values():
            if function_instance.should_calculate(
                monitor=monitor, metric_name=metric_name
            ):
                result.append(function_instance)

        MONITOR_METRIC_TO_FUNCTIONS_CACHE[cache_key] = result

    return MONITOR_METRIC_TO_FUNCTIONS_CACHE[cache_key]


def clear_registry_cache():
    global MONITOR_METRIC_TO_FUNCTIONS_CACHE

    LOG.debug("Clearing registry cache")

    MONITOR_METRIC_TO_FUNCTIONS_CACHE = {}


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
