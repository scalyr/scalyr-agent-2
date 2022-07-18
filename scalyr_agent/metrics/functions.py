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
    from typing import Union
    from typing import Tuple

    from scalyr_agent.scalyr_monitor import ScalyrMonitor  # NOQA

import time

from abc import ABCMeta
from abc import abstractmethod
from collections import defaultdict

import six


class MetricFunction(six.with_metaclass(ABCMeta)):
    # Suffix which get's added to the derived metric name. For example, if metric name is
    # "cpu.seconds_total", derived rate metric would be named "cpu.seconds_total_rate"
    METRIC_SUFFIX = ""  # type: str

    @classmethod
    @abstractmethod
    def should_calculate(cls, monitor, metric_name):
        # type: (ScalyrMonitor, six.text_type) -> bool
        """
        Return True if this function should be calculated for the provided metric.
        """
        pass

    @classmethod
    @abstractmethod
    def calculate(cls, monitor, metric_name, metric_value, timestamp):
        # type: (ScalyrMonitor, six.text_type, Union[int, float], Optional[int]) -> Optional[List[Tuple[str, float]]]
        """
        Run function on the provided metric and return any derived metrics which should be emitted.

        :param monitor: ScalyrMonitor instance.
        :param metric_name: Metric name.
        :param metric_value: Metric value.
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
    # Maps <monitor name + monitor instance id short hash>.<metric name> to a tuple
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
    MAX_RATE_METRICS_COUNT_WARN = 5000

    MAX_RATE_METRIC_WARN_MESSAGE = """
Tracking client side rate for over %s metrics. Tracking and calculating rate for that many metrics
could add overhead in terms of CPU and memory usage.
    """.strip() % (
        MAX_RATE_METRICS_COUNT_WARN
    )

    @classmethod
    def calculate(cls, monitor, metric_name, metric_value, timestamp=None):
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
        :param timestamp: Optional metric timestamp in ms.
        """
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
        # qualified monitor name
        dict_key = monitor.short_hash + "." + metric_name

        (
            previous_collection_timestamp,
            previous_metric_value,
        ) = cls.RATE_CALCULATION_METRIC_VALUES[dict_key]

        if previous_collection_timestamp is None or previous_metric_value is None:
            # If this is first time we see this metric, we just store the value sine we don't have
            # previous sample yet to be able to calculate rate
            monitor._logger.debug(
                'No previous data yet for metric "%s", unable to calculate rate yet.'
                % (metric_name)
            )

            cls.RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
            return None

        if timestamp_s <= previous_collection_timestamp:
            monitor._logger.debug(
                'Current timestamp for metric "%s" is smaller or equal to current timestamp, cant '
                "calculate rate (timestamp_previous=%s,timestamp_current=%s)"
                % (metric_name, previous_collection_timestamp, timestamp_s)
            )
            return None

        # If time delta between previous and current collection timestamp is too large, we ignore
        # the previous value (but we still store the latest value for future rate calculations)
        if (
            timestamp_s - previous_collection_timestamp
        ) >= cls.MAX_RATE_TIMESTAMP_DELTA_SECONDS:
            monitor._logger.debug(
                'Time delta between previous and current metric collection timestamp for metric "%s"'
                "is larger than %s seconds, ignoring rate calculation (timestamp_previous=%s,timestamp_current=%s)"
                % (
                    metric_name,
                    cls.MAX_RATE_TIMESTAMP_DELTA_SECONDS,
                    previous_collection_timestamp,
                    timestamp_s,
                )
            )

            cls.RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
            return None

        # NOTE: Metrics for which we calculate rates need to be counters. This means they
        # should be increasing over time. If new value is < old value, we skip calculation (same
        # as the current server side implementation)
        if metric_value < previous_metric_value:
            monitor._logger.debug(
                'Current metric value for metric "%s" is smaller than previous value (current_value=%s,previous_value=%s)'
                % (metric_name, metric_value, previous_metric_value)
            )
            return None

        rate_value = round(
            (metric_value - previous_metric_value)
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
            'Calculated rate "%s" for metric "%s" (previous_collection_timestamp=%s,previous_metric_value=%s,current_timestamp=%s,current_value=%s)'
            % (
                rate_value,
                metric_name,
                previous_collection_timestamp,
                previous_metric_value,
                timestamp_s,
                metric_value,
            ),
        )

        rate_metric_name = "%s%s" % (metric_name, cls.METRIC_SUFFIX)
        # TODO: Use dataclass once we only support Python 3
        result = [(rate_metric_name, rate_value)]
        return result

    @classmethod
    def should_calculate(cls, monitor, metric_name):
        """
        Return True if client side rate should be calculated for the provided metric.
        """
        if not monitor or not monitor._global_config:
            return False

        config_entry_key = "%s:%s" % (monitor.monitor_module_name, metric_name)

        config_calculate_rate_metric_names = (
            monitor._global_config.calculate_rate_metric_names
        )
        monitor_calculate_rate_metric_names = monitor.get_calculate_rate_metric_names()

        return (
            config_entry_key in config_calculate_rate_metric_names
            or config_entry_key in monitor_calculate_rate_metric_names
        )

    @classmethod
    def clear_cache(cls):
        cls.RATE_CALCULATION_METRIC_VALUES = defaultdict(lambda: (None, None))
