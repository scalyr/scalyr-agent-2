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
This module contains various functions which can be applied to metrics to calculate derived values
such as rates, derivatives, aggregations, etc.
"""

if False:
    from typing import Optional
    from typing import List
    from typing import Tuple
    from typing import Dict
    from typing import Any
    from typing import Union

    from scalyr_agent.scalyr_monitor import ScalyrMonitor  # NOQA

import time

from abc import ABCMeta
from abc import abstractmethod
from collections import defaultdict
from itertools import chain

import six

from scalyr_agent.util import get_hash_for_flat_dictionary
from scalyr_agent.util import get_flat_dictionary_memory_usage
from scalyr_agent.instrumentation.timing import get_empty_stats_dict
from scalyr_agent.instrumentation.decorators import time_function_call
from scalyr_agent.scalyr_logging import getLogger
from scalyr_agent.scalyr_logging import LazyOnPrintEvaluatedFunction

LOG = getLogger(__name__)

# Dictionary which stores timing / run time information for "RateMetricFunction.calculate()"
# method
RATE_METRIC_CALCULATE_RUNTIME_STATS = get_empty_stats_dict()


class MetricFunction(six.with_metaclass(ABCMeta)):
    # Suffix which get's added to the derived metric name. For example, if metric name is
    # "cpu.seconds_total", derived rate metric would be named "cpu.seconds_total_rate"
    METRIC_SUFFIX = ""  # type: str

    @classmethod
    @abstractmethod
    def should_calculate_for_monitor_and_metric(cls, monitor, metric_name):
        # type: (ScalyrMonitor, six.text_type) -> bool
        """
        Return True if rate should be calculated for the provided monitor and metric name.

        This function is used for internal (monitor_name, metric_name) cache and additional filtering
        which takes extra_field values into account is performed when "calculate()" method is called.
        """
        pass

    @classmethod
    @abstractmethod
    def should_calculate(cls, monitor, metric_name, extra_fields=None):
        # type: (ScalyrMonitor, six.text_type, Optional[Dict[str, Any]]) -> bool
        """
        Return True if this function should be calculated for the provided metric.
        """
        pass

    @classmethod
    @abstractmethod
    def calculate(
        cls, monitor, metric_name, metric_value, extra_fields=None, timestamp=None
    ):
        # type: (ScalyrMonitor, six.text_type, Union[int, float], Optional[Dict[str,Any]], Optional[int]) -> Optional[List[Tuple[str, float]]]
        """
        Run function on the provided metric and return any derived metrics which should be emitted.

        :param monitor: ScalyrMonitor instance.
        :param metric_name: Metric name.
        :param metric_value: Metric value.
        :param extra_fields: Optional dictionary with metric extra fields.
        :param timestamp: Optional timestamp of metric collection in ms. If not provided, we
                          default to current time.
        """
        pass

    @classmethod
    def clear_cache(cls):
        # type: () -> None
        """
        Clear any internal cache used by the class (if any).
        """
        pass


class RateMetricFunction(MetricFunction):
    METRIC_SUFFIX = "_rate"

    # Stores metric values and timestamp for the metrics which we calculate per second rate in the
    # agent.
    # Maps <monitor name + monitor instance id short hash>.<metric name>.<extra fields hash> to a tuple
    # (<timestamp_of_previous_colection>, <previously_collected_value>).
    # To avoid collisions across monitors (same metric name can be used by multiple monitors), we prefix
    # metric name with a short hash of the monitor FQDN (<monitor module>.<monitor class name>) +
    # monitor instance id. We use a short hash and not fully qualified monitor name to reduce memory
    # usage a bit.
    # NOTE: Those values are not large, but we should probably still implement some kind of watch dog
    # job where we periodically purge out entries for values which are older than MAX_RATE_TIMESTAMP_DELTA_SECONDS
    # (since those won't be used for calculation anyway).
    RATE_CALCULATION_METRIC_VALUES = defaultdict(lambda: (None, None))

    # If the time delta between previous metric collection timestamp value and current metric collection
    # timestamp value is longer than this amount of seconds (11 minutes by default), we will ignore
    # previous value and not calculate the rate with old / stale metric value.
    MAX_RATE_TIMESTAMP_DELTA_SECONDS = 11 * 60

    # If we track rate for more than this many metrics, a warning will be emitted.
    MAX_RATE_METRICS_COUNT_WARN = 15000

    MAX_RATE_METRIC_WARN_MESSAGE = """
Tracking client side rate for over %s metrics. Tracking and calculating rate for that many metrics
could add overhead in terms of CPU and memory usage.
    """.strip() % (
        MAX_RATE_METRICS_COUNT_WARN
    )

    LAZY_PRINT_CACHE_SIZE_LENGTH = LazyOnPrintEvaluatedFunction(
        lambda: len(RateMetricFunction.RATE_CALCULATION_METRIC_VALUES)
    )
    LAZY_PRINT_CACHE_SIZE_BYTES = LazyOnPrintEvaluatedFunction(
        lambda: get_flat_dictionary_memory_usage(
            RateMetricFunction.RATE_CALCULATION_METRIC_VALUES
        )
    )

    LAZY_PRINT_TIMING_MIN = LazyOnPrintEvaluatedFunction(
        lambda: RATE_METRIC_CALCULATE_RUNTIME_STATS["min"]
    )
    LAZY_PRINT_TIMING_MAX = LazyOnPrintEvaluatedFunction(
        lambda: RATE_METRIC_CALCULATE_RUNTIME_STATS["max"]
    )
    LAZY_PRINT_TIMING_AVG = LazyOnPrintEvaluatedFunction(
        lambda: RATE_METRIC_CALCULATE_RUNTIME_STATS["avg"]
    )

    @classmethod
    @time_function_call(RATE_METRIC_CALCULATE_RUNTIME_STATS, 0.001)
    def calculate(
        cls, monitor, metric_name, metric_value, extra_fields=None, timestamp=None
    ):
        """
        Calculate per second rate for the provided metric name (if configured to do so).

        The formula used is:

            (<current metric value> - <previous metric value>) / (<current collection timestamp in seconds> - <previous collection timestamp in seconds>)

        This method also takes into account and handles the following scenarios:

            - Metric value is not a number
            - New metric value is smaller than previous one
            - New metric collection timestamp is smaller or equal to the previous one
            - Time delta between current and previous metric collection timestamp is larged than the
              defined upper bound

        :param monitor: Monitor instance.
        :param metric_name: Metric name,
        :param metric_value: Metric value.
        :param extra_fields: Optional metric extra fields.
        :param timestamp: Optional metric timestamp in ms.
        """
        if not cls.should_calculate(
            monitor=monitor, metric_name=metric_name, extra_fields=extra_fields
        ):
            return None

        if timestamp:
            timestamp_s = timestamp / 1000
        else:
            timestamp_s = int(time.time())

        if not isinstance(metric_value, (int, float)):
            limit_key = "%s-nan" % (metric_name)
            monitor._logger.warn(
                'Metric "%s" is not a number. Cannot calculate rate.' % (metric_name),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )
            return None

        # To avoid collisions across multiple monitors (same metric name being used by multiple
        # monitors), we prefix data in internal dictionary with the short hash of the fully
        # qualified monitor name.
        # Since same metric name can be used by values with different extra fields, we also include
        # extra fields as part of the dictionary key.
        extra_fields_hash = get_hash_for_flat_dictionary(extra_fields)
        dict_key = monitor.short_hash + "." + metric_name + "." + extra_fields_hash

        (
            previous_collection_timestamp,
            previous_metric_value,
        ) = cls.RATE_CALCULATION_METRIC_VALUES[dict_key]

        if previous_collection_timestamp is None or previous_metric_value is None:
            # If this is first time we see this metric, we just store the value sine we don't have
            # previous sample yet to be able to calculate rate
            monitor._logger.debug(
                'No previous data yet for metric "%s", unable to calculate rate yet (extra_fields=%s).'
                % (metric_name, extra_fields)
            )

            cls.RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
            return None

        if timestamp_s <= previous_collection_timestamp:
            monitor._logger.debug(
                'Current timestamp for metric "%s" is smaller or equal to current timestamp, cant '
                "calculate rate (timestamp_previous=%s,timestamp_current=%s,extra_fields=%s)"
                % (
                    metric_name,
                    previous_collection_timestamp,
                    timestamp_s,
                    str(extra_fields),
                )
            )
            return None

        # If time delta between previous and current collection timestamp is too large, we ignore
        # the previous value (but we still store the latest value for future rate calculations)
        if (
            timestamp_s - previous_collection_timestamp
        ) >= cls.MAX_RATE_TIMESTAMP_DELTA_SECONDS:
            monitor._logger.debug(
                'Time delta between previous and current metric collection timestamp for metric "%s"'
                "is larger than %s seconds, ignoring rate calculation (timestamp_previous=%s,timestamp_current=%s,extra_fields=%s)"
                % (
                    metric_name,
                    cls.MAX_RATE_TIMESTAMP_DELTA_SECONDS,
                    previous_collection_timestamp,
                    timestamp_s,
                    str(extra_fields),
                )
            )

            cls.RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
            return None

        # NOTE: Metrics for which we calculate rates need to be counters. This means they
        # should be increasing over time. If new value is < old value, we skip calculation (same
        # as the current server side implementation)
        if metric_value < previous_metric_value:
            monitor._logger.debug(
                'Current metric value for metric "%s" is smaller than previous value (current_value=%s,previous_value=%s,extra_fields=%s)'
                % (metric_name, metric_value, previous_metric_value, str(extra_fields))
            )
            return None

        rate_value = round(
            (float(metric_value) - previous_metric_value)
            / (timestamp_s - previous_collection_timestamp),
            5,
        )

        cls.RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)

        if len(cls.RATE_CALCULATION_METRIC_VALUES) > cls.MAX_RATE_METRICS_COUNT_WARN:
            # Warn if we are tracking rate for a large number of metrics which could cause
            # performance issues / overhead
            monitor._logger.warn(
                cls.MAX_RATE_METRIC_WARN_MESSAGE,
                limit_once_per_x_secs=86400,
                limit_key="rate-max-count-reached",
            )

        monitor._logger.debug(
            'Calculated rate "%s" for metric "%s" (previous_collection_timestamp=%s,previous_metric_value=%s,current_timestamp=%s,current_value=%s,extra_fields=%s)'
            % (
                rate_value,
                metric_name,
                previous_collection_timestamp,
                previous_metric_value,
                timestamp_s,
                metric_value,
                str(extra_fields),
            ),
        )

        rate_metric_name = "%s%s" % (metric_name, cls.METRIC_SUFFIX)
        # TODO: Use dataclass once we only support Python 3
        result = [(rate_metric_name, rate_value)]

        # Periodically print cache size and function timing information
        log_interval = (
            monitor._global_config
            and monitor._global_config.instrumentation_stats_log_interval
            or 0
        )
        if log_interval > 0:
            LOG.info(
                "agent_instrumentation_stats key=monitor_rate_metric_calculation_values_cache_stats cache_entries=%s cache_size_bytes=%s",
                cls.LAZY_PRINT_CACHE_SIZE_LENGTH,
                cls.LAZY_PRINT_CACHE_SIZE_BYTES,
                limit_key="mon-met-rate-cache-stats",
                limit_once_per_x_secs=log_interval,
            )

            LOG.info(
                "agent_instrumentation_stats key=agent_rate_func_calculate_timing_stats avg=%s min=%s max=%s",
                cls.LAZY_PRINT_TIMING_AVG,
                cls.LAZY_PRINT_TIMING_MIN,
                cls.LAZY_PRINT_TIMING_MAX,
                limit_key="mon-rate-calc-timing-stats",
                limit_once_per_x_secs=log_interval,
            )

        return result

    @classmethod
    def should_calculate_for_monitor_and_metric(cls, monitor, metric_name):
        """
        Return True if rate should be calculated for the provided monitor and metric name.

        This function is used for internal (monitor_name, metric_name) cache and additional filtering
        which takes extra_field values into account is performed when "calculate()" method is called.
        """
        if not monitor or not monitor._global_config:
            return False

        config_calculate_rate_metric_names = (
            monitor._global_config.calculate_rate_metric_names
        )
        monitor_calculate_rate_metric_names = monitor.get_calculate_rate_metric_names()

        # Partial entry key without extra fields suffix
        config_entry_key = "%s:%s" % (monitor.monitor_module_name, metric_name)

        for config_value in chain(
            config_calculate_rate_metric_names, monitor_calculate_rate_metric_names
        ):
            has_extra_fields_filter = config_value.count(":") == 2

            if has_extra_fields_filter:
                config_value_without_extra_fields_filter = config_value.rsplit(":", 1)[
                    0
                ]
            else:
                config_value_without_extra_fields_filter = config_value

            # Direct simple metric name only match with no additional extra fields filters
            if config_value_without_extra_fields_filter == config_entry_key:
                return True

        return False

    @classmethod
    def should_calculate(cls, monitor, metric_name, extra_fields=None):
        """
        Return True if client side rate should be calculated for the provided metric name and
        extra_fields values.
        """
        extra_fields = extra_fields or {}

        if not monitor or not monitor._global_config:
            return False

        config_calculate_rate_metric_names = (
            monitor._global_config.calculate_rate_metric_names
        )
        monitor_calculate_rate_metric_names = monitor.get_calculate_rate_metric_names()

        # Config values follow this notation: <monitor module name>:<metric name>:<optional extra field value>
        # For example: openmetrics_monitor:docker.cpu_usage_seconds_total:mode=kernel

        # Partial entry key without extra fields suffix
        config_entry_key = "%s:%s" % (monitor.monitor_module_name, metric_name)

        for config_value in chain(
            config_calculate_rate_metric_names, monitor_calculate_rate_metric_names
        ):
            # Direct simple metric name only match
            if config_value == config_entry_key:
                return True
            elif (
                extra_fields
                and config_value.count(":") == 2
                and config_value.count("=") == 1
            ):
                config_extra_field_name, config_extra_field_value = config_value.split(
                    ":"
                )[-1].split("=")
                if (
                    extra_fields.get(config_extra_field_name, None)
                    == config_extra_field_value
                ):
                    return True

        return False

    @classmethod
    def clear_cache(cls):
        cls.RATE_CALCULATION_METRIC_VALUES = defaultdict(lambda: (None, None))
