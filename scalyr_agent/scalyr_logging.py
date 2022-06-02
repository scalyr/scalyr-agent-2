# Copyright 2014 Scalyr Inc.
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
#
# The Scalyr-specific extensions to the normal python Logger classes.  In particular, this provides
# a new AgentLogger class that extends logging.Logger to implement new features:
#   - Reporting metric values in a standard format (which can be parsed by the Scalyr servers)
#   - Rate limiting the number of bytes written to the agent log file (using a "leaky bucket" algorithm to
#       calculate the allowed number of bytes to write)
#   - Aggregating records reported from different modules into a central agent log
#   - Limit the frequency specific records are emitted (e.g., specifying that a particular record
#     should only be emitted at most once per X seconds).
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

if False:  # NOSONAR
    from typing import Dict
    from typing import Optional
    from typing import Union

    # Workaround for a cyclic import - scalyr_monitor depends on scalyr_logging and vice versa
    from scalyr_agent.scalyr_monitor import ScalyrMonitor

import logging
import logging.handlers
import os
import re
import sys
import time
import threading
import io
import inspect
from collections import defaultdict

import six

import scalyr_agent.util as util
from scalyr_agent.util import RateLimiter

if six.PY2:
    _METRIC_NAME_SUPPORTED_TYPES = (six.text_type, six.binary_type)
    _METRIC_VALUE_SUPPORTED_TYPES = (
        six.text_type,
        six.binary_type,
        bool,
        float,
    ) + six.integer_types
else:
    _METRIC_NAME_SUPPORTED_TYPES = (six.text_type,)
    _METRIC_VALUE_SUPPORTED_TYPES = (six.text_type, bool, float) + six.integer_types

# The debugging levels supported on the debugger logger.  The higher the debug level, the
# more verbose the output.
DEBUG_LEVEL_0 = logging.INFO
DEBUG_LEVEL_1 = logging.DEBUG
DEBUG_LEVEL_2 = 7
DEBUG_LEVEL_3 = 6
DEBUG_LEVEL_4 = 5
DEBUG_LEVEL_5 = 4

# Stores metric values and timestamp for the metrics which we calculate per second rate on the
# agent.
# Maps <monitor name + monitor instance id short hash>.<metric name> to a tuple
# (<timestamp_of_previous_colection>, <previously_collected_value>).
# To avoid collisions across monitors (same metric name can be used by multiple monitors), we prefix
# metric name with a short hash of the monitor FQDN (<monitor module>.<monitor class> name). We
# use a short hash and not fully qualified monitor name to reduce memory usage a bit.
# NOTE: Those values are not large but we should probably still implement some kind of watch dog
# timer where we periodically purge out entries for values which are older than MAX_RATE_TIMESTAMP_DELTA_SECONDS
# (since those won't be used for calculation anyway).
RATE_CALCULATION_METRIC_VALUES = defaultdict(lambda: (None, None))

# If the time delta between previous metric value and current metric value is longer than this
# amount of seconds (11 minutes by default), we will ignore previous value and not calculate the
# rate with old metric value.
MAX_RATE_TIMESTAMP_DELTA_SECONDS = 11 * 60

# If we track rate for more than this many metrics, a warning will be emitted.
MAX_RATE_METRICS_COUNT_WARN = 5000

MAX_RATE_METRIC_WARN_MESSAGE = """
Tracking client side rate for over %s metrics. Tracking and calculating rate for that many metrics
could add overhead in terms of CPU and memory usage.
""".strip() % (
    MAX_RATE_METRICS_COUNT_WARN
)

# Stores a list of "reserved" event level attribute names. If we detect metric extra field with this
# name we sanitize / escape it by adding "_" suffix to the field name. This way we avoid possible
# collisions with those special / reserved names which could break some tsdb related queries and
# functionality.
RESERVED_EVENT_ATTRIBUTE_NAMES = [
    "logfile",
    "monitor",
    "metric",
    "value",
    "instance",
    "severity",
]


def clear_rate_cache():
    """
    Clear internal cache where we store metric values we need to calculate per second rates for
    whitelisted metrics.
    """
    global RATE_CALCULATION_METRIC_VALUES
    RATE_CALCULATION_METRIC_VALUES = defaultdict(lambda: (None, None))


# noinspection PyPep8Naming
def getLogger(name):
    """Returns a logger instance to use for the given name that implements the Scalyr agent's extra logging features.

    This should be used in place of logging.getLogger when trying to retrieve a logging instance that implements
    Scalyr agent's extra features.

    Note, the logger instance will be configured to emit records at INFO level and above.

    @param name: The name of the logger, such as the module name. If this is for a particular monitor instance, then
        the monitor id should be appended at the end surrounded by brackets, such as "my_monitor[1]"

    @return: A logger instance implementing the extra features.
    """
    logging.setLoggerClass(AgentLogger)
    result = logging.getLogger(name)
    result.setLevel(logging.INFO)
    return result


# The single AgentLogManager instance that tracks all of the process wide information necessary to implement
# our logging strategy.  This variable is set to the real variable down below.
__log_manager__ = None


def set_log_destination(
    use_stdout=False,
    use_disk=False,
    no_fork=False,
    stdout_severity="NOTSET",
    logs_directory=None,
    agent_log_file_path="agent.log",
    agent_debug_log_file_suffix="_debug",
    max_bytes=20 * 1024 * 1024,
    backup_count=2,
    log_write_rate=2000,
    max_write_burst=100000,
):
    """Updates where the log records are written for the Scalyr-controlled logs, such as the main agent log,
    the metric logs, and the debug log.

    Note, this will remove all other handlers from the root logger.  If you have non-Scalyr handlers added, they
    will be removed.  For tests and run this is running at the Scalyr Agent, that should be fine.  This is necessary
    to allow unit test to call this method multiple times and have their logging output captured by the unittest
    framework.

    The three main log files generated by the AgentLogger instances are:
      - agent.log:  Holds all normal log records with levels of logging.INFO or greater generated by any AgentLogger
          instance, which are typically passed to agent-related modules or retrieved using scalyr_logging.getLogger.
          The path for this file can be changed by using the agent_log_file_path argument on this method.
      - metric logs:  These are log files containing the metrics records created using the 'emit_value' method
          on AgentLogger instances.  The name of the metric logs are controlled by the monitor plugins that created
          them but generally use the module name and are placed in the logs directory.
      - agent_debug.log:  Holds all log records with levels of logging.DEBUG or lower generated by any AgentLogger
          instance.  The path for this log file is always based on the main agent log file path.  By default, it is the
          same file name just with _debug inserted right before the first period in the file name.  This log is only
          created and written to if the agent is configured to emit debug messages.

    If use_stdout is True, then all of the logs mentioned above are sent to stdout.  If not, then the logs are
    written to disk, using the paths discussed above.

    This method is not thread safe.

    @param use_stdout: True if the logs should be sent to standard out.  If this is False, then use_disk must be true.
    @param use_disk:  True if the logs should be sent to disk.  If this is False, then use_stdout must be true.
    @param no_fork:  True if we are running in --no-fork mode, logs above a configured severity threshold will be
        written to stdout.
    @param stdout_severity: Logs at or above this severity level will be written to stdout if no_fork is true.
    @param logs_directory:  The path of the directory to, by default, write log files.
    @param agent_log_file_path: If not None, then the file path where the main agent log file should be written
        using a RotatingLogHandler scheme, with parameters specified by max_bytes and backup_count.  If the path is
        not absolute, then it is relative to logs_directory.
    @param agent_debug_log_file_suffix: The suffix to insert before the first period in the main agent log file name
        to create the debug file name.
    @param max_bytes: The maximum number of bytes written to any log file before it is rotated.
    @param backup_count: The number of previously rotated logs to keep.
    @param log_write_rate: The average number of bytes per second to allow to be written to the log files. When this
        rate limit is exceeded, new log records are ignored. When log records can be accepted again, an additional line
        is written to the log to record how many records were ignored. This variable is essentially the fill rate used
        by the "leaky-bucket" algorithm used to rate limit the log write rate.
    @param max_write_burst: The short term maximum burst write rate allowed to be written to the log. This is
        essentially the maximum bucket size used by the "leaky-bucket" algorithm used to rate limit the log write rate.
    """
    # Just delegate to the manager's implementation.
    __log_manager__.set_log_destination(
        use_stdout=use_stdout,
        use_disk=use_disk,
        no_fork=no_fork,
        stdout_severity=stdout_severity,
        logs_directory=logs_directory,
        agent_log_file_path=agent_log_file_path,
        agent_debug_log_file_suffix=agent_debug_log_file_suffix,
        max_bytes=int(max_bytes),
        backup_count=int(backup_count),
        log_write_rate=log_write_rate,
        max_write_burst=max_write_burst,
    )


def set_log_level(level, debug_level_logger_names=None):
    """Sets the log level that should be used by all AgentLogger instances and if debug_level_logger_names
    is set, also set log level for the specific loggers to debug.

    This method is thread-safe.

    @param level: The level, in the logging units by the logging package, such as logging.INFO, logging.DEBUG, etc.
        You can also use one of the Scalyr debug levels, such as DEBUG_LEVEL_0, DEBUG_LEVEL_1, etc.
    @type level: int
    """
    # 1. Set global log level for all the loggers
    __log_manager__.set_log_level(level)

    # 2. Set debug level for specific loggers (if enabled)
    if debug_level_logger_names:
        loggers = [
            logging.getLogger(logger_name) for logger_name in debug_level_logger_names
        ]
        __log_manager__.set_log_level_for_loggers(loggers=loggers, level=DEBUG_LEVEL_5)


def get_logger_names():
    """
    Return name of all the currently instantiated and valid loggers.
    """
    # pylint: disable=no-member
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    # pylint: enable=no-member
    logger_names = [logger.name for logger in loggers]
    return logger_names


#
# _srcfile is used when walking the stack to check when we've got the first
# caller stack frame.  This is copied from the logging/__init__.py
#
def __determine_file():
    # To determine file holding this code, we do not rely on __file__ because it is not portable to all
    # versions of python, especially when on win32 when code is running using PyInstaller.  Instead, we do this
    # trick which is suppose to be more portable.
    base = os.getcwd()
    file_path = inspect.stack()[1][1]
    if not os.path.isabs(file_path):
        file_path = os.path.join(base, file_path)
    file_path = os.path.dirname(os.path.realpath(file_path))
    return file_path


_srcfile = os.path.normcase(__determine_file())


# next bit filched from 1.5.2's inspect.py
def currentframe():
    """Return the frame object for the caller's stack frame."""
    # noinspection PyBroadException
    try:
        raise Exception
    except Exception:
        return sys.exc_info()[2].tb_frame.f_back


# noinspection PyPep8Naming
def alternateCurrentFrame():
    # noinspection PyProtectedMember
    return sys._getframe(3)


# We set this variable to True after close_handlers() has been called (this happens when termination
# handler function is called when shutting down the agent.
# This way we can avoid "IOError: [Errno 0] Error" errors which may appear in stdout on agent
# shutdown when using agent_main.py stop command which sends SIGTERM signal multiple times.
# Those logs appeared if we try to log a message inside SIGTERM handler after all the log
# handlers have already been closed.
HANDLERS_CLOSED = False


def close_handlers():
    global HANDLERS_CLOSED

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

        if handler is not None:
            handler.close()

    HANDLERS_CLOSED = True


if hasattr(sys, "_getframe"):
    currentframe = alternateCurrentFrame  # NOQA
# done filching


# noinspection PyPep8Naming
class AgentLogger(logging.Logger):
    """Custom logger to use for logging information, errors, and metrics from the Scalyr agent.

    These instances are returned by scalyr_agent.getLogger.  You should use that method in place of logging.getLogger.

    The main additions are:
        metrics:  Using the 'emit_value' method, metric values may be emitted to the appropriate log file using
            a standard format that can be easily parsed by the Scalyr servers.  Note,
            not all Logger instances are allowed to invoke 'emit_value'.  Only ones whose 'openMetricFileForMonitor'
            method has been invoked.  This is typically done for all Logger instances passed to Scalyr monitor modules.
        component:  We define our own concept of component which is suppose to record the general subsystem
            that generated the log record.  The components could be 'core' or one of the metric monitors.
        error_code:  All log methods (such as log, warn, error) can take in a keyword-value argument with
            key 'error_code' which will record the error code (a str) for the log record.  This error code will
            be included in the emitted output, formatted in a consistent way.
        custom format:  Our own custom format is automatically added to all outputted lines.
        limit_once_per_x_secs:  On any emitting method such as 'log', 'info', 'warn',
            'error, etc, you may pass in the additional arguments of 'limit_once_per_x_secs' and 'limit_key'
            to limit how often that particular record is emitted to the log.  The 'limit_once_per_x_secs' specifies
            the minimum number of seconds since the last time a record was emitted with the same limit_key for this
            record to be emitted.  The 'limit_key' is an arbitrary string that is used to identify the set of records
            that should be considered.

    The log level for all AgentLogger instances are controlled in a central way.  By default, they are all set to
    logging.INFO.  However, this can be changed using the agent configuration file.  You may request for more
    verbose logging to be sent to the debug log.  There are five different debug levels defined by Scalyr for
    consistency, ranging from DEBUG_LEVEL_0 for no debugging (equal to logging.INFO) to DEBUG_LEVEL_5 for very
    verbose debug logging.
    """

    # The regular expression that must match for metric and field names.  Essentially, it has to begin with
    # a letter or underscore, and only contain letters, digits, periods, underscores, and dashes.  If you change this,
    # be sure to fix the force_valid_metric_or_field_name method below.
    __metric_or_field_name_rule = re.compile(r"[_a-zA-Z][\w\.\-]*$")

    def __init__(self, name):
        """Initializes the logger instance with the specified name.

        The logger will base the component and the monitor id on the name.  If the name ends in "[.*]" then
        the monitor id will be set to whatever is inside the brackets.  If the name refers to module in the Scalyr
        Agent package, then component will be set to core, otherwise it will be set to 'monitor:XXX' where XXX is
        the last component of the name split by periods (and excluding the monitor id).

        @param name: The name, typically the module name with the possible addition of the monitor id sourrouned by
            brackets.
        """
        self.__logger_name = name

        # Look for the monitor id, which is at the end surrounded by brackets.
        m = re.match(r"([^\[]*)(\(.*\))", name)
        if m:
            module_path = m.group(1)
            self.__monitor_id = m.group(2)[1:-1]
        else:
            # 2->TODO In python2 the 'name' variable with be 'str' in __name__ is passed to this constructor.
            module_path = six.ensure_text(name)
            self.__monitor_id = None

        # If it is from the scaly_agent module, then it is 'core' unless it is one of the monitors.
        if (
            module_path.find("scalyr_agent") == 0
            and not module_path.find("scalyr_agent.builtin_monitors.") == 0
        ):
            self.component = "core"
            self.monitor_name = None
            self.monitor_name_base = None
        else:
            # Note, we only use the last part of the module name for the name we use in the logs.  We rely on the
            # monitor_id to make it unique.  This is calculated in configuration.py.  We need to make sure this
            # code is in sync with that file.
            self.monitor_name_base = module_path.split(".")[-1]
            if self.__monitor_id is not None:
                self.monitor_name = "%s(%s)" % (
                    self.monitor_name_base,
                    self.__monitor_id,
                )
            else:
                self.monitor_name = self.monitor_name_base

            self.component = "monitor:%s" % self.monitor_name

        # If this logger is for a particular monitor instance, then we will eventually call openMetricLoggerForMonitor
        # on it to set which output file its metrics should be reported.  When that happens, these will be set to
        # which monitor it is reporting for and the associated log handler.
        self.__monitor = None
        self.__metric_handler = None

        # Used in debugging tests.  If true, the abstraction will save a reference to the last record created.
        self.__keep_last_record = False
        self.__last_record = None

        # A dict that maps limit_keys to the last time any record has been emitted that used that key.  This is
        # used to implement the limit_once_per_x_secs feature.
        self.__log_emit_times = {}

        logging.Logger.__init__(self, name)

        global __log_manager__

        # Be sure to add this to the manager's list of logger instances.  This will also set the log level to the
        # right level.
        __log_manager__.add_logger_instance(self)

    def _should_calculate_metric_rate(self, monitor, metric_name):
        # type: (ScalyrMonitor, str) -> bool
        """
        Return True if client side rate should be calculated for the provided metric.
        """
        if not monitor or not monitor._global_config:
            return False

        config_calculate_rate_metric_names = (
            monitor._global_config.calculate_rate_metric_names
        )
        monitor_calculate_rate_metric_names = monitor.get_calculate_rate_metric_names()

        return (
            metric_name in config_calculate_rate_metric_names
            or metric_name in monitor_calculate_rate_metric_names
        )

    def _calculate_metric_rate(
        self, monitor, metric_name, metric_value, timestamp=None
    ):
        # type: (ScalyrMonitor, str, Union[int, float], Optional[int]) -> Optional[float]
        """
        Calculate rate for the provided metric name (if configured to do so).

        :param monitor: Monitor instance.
        :param metric_name: Metric name,
        :param metric_value: Metric value.
        :param timestamp: Optional metric timestamp in ms.
        """
        if not self._should_calculate_metric_rate(
            monitor=monitor, metric_name=metric_name
        ):
            return None

        if timestamp:
            timestamp_s = timestamp / 1000
        else:
            timestamp_s = timestamp or int(time.time())

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
        ) = RATE_CALCULATION_METRIC_VALUES[dict_key]

        if previous_collection_timestamp is None or previous_metric_value is None:
            # If this is first time we see this metric, we just store the value sine we don't have
            # previous sample yet to be able to calculate rate
            monitor._logger.debug(
                'No previous data yet for metric "%s", unable to calculate rate yet.'
                % (metric_name)
            )

            RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
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
        ) >= MAX_RATE_TIMESTAMP_DELTA_SECONDS:
            monitor._logger.debug(
                'Time delta between previous and current metric collection timestamp for metric "%s"'
                "is larger than %s seconds, ignoring rate calculation (timestamp_previous=%s,timestamp_current=%s)"
                % (
                    metric_name,
                    MAX_RATE_TIMESTAMP_DELTA_SECONDS,
                    previous_collection_timestamp,
                    timestamp_s,
                )
            )

            RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)
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

        RATE_CALCULATION_METRIC_VALUES[dict_key] = (timestamp_s, metric_value)

        if len(RATE_CALCULATION_METRIC_VALUES) > MAX_RATE_METRICS_COUNT_WARN:
            # Warn if we are tracking rate for a large number of metrics which could cause
            # performance issues / overhead
            monitor._logger.warn(
                MAX_RATE_METRIC_WARN_MESSAGE,
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
        return rate_value

    def emit_value(
        self,
        metric_name,
        metric_value,
        extra_fields=None,
        monitor=None,
        monitor_id_override=None,
        timestamp=None,
    ):
        """Emits a metric and its value to the underlying log to be transmitted to Scalyr.

        Adds a new line to the metric log recording the specified value for the metric.  Additional fields
        may be added to this line using extra_fields, which can then be used in Scalyr searches to further limit
        the metric values being aggregated together.  For example, you may wish to report a free memory metric,
        but have an additional field of 'type=buffer' so that you can easily graph all free memory as well as
        free memory just from buffers.

        Note, this method may only be called after the metric file for the monitor has been opened.  This is always
        done before the monitor's "run" method is invoked.

        @param metric_name: The string containing the name for the metric.
        @param metric_value: The value for the metric. The only allowed types are int, long, float, bool and
        six.text_type.
        @param extra_fields: An optional dict that if specified, will be included as extra fields on the log line.
            These fields can be used in future searches/graphs expressions to restrict which specific instances of the
            metric are matched/aggregated together. The keys for the dict must be six.text_type and the only allowed
            value types are int, long, float, bool, and six.text_type.
        @param monitor: The ScalyrMonitor instance that is reporting the metric. Typically, this does not need to be
            supplied because it defaults to whatever monitor for each the logger was created.
        @param monitor_id_override:  Used to change the reported monitor id for this metric just for the purposes
            of reporting this one value.  The base monitor name will remain unchanged.
        @type metric_name: six.text_type
        @raise UnsupportedValueType: If the value type is not one of the supported types.
        @param timestamp: Optional timestamp in milliseconds to use for this log record. If not specified, it uses
            current time when creating a Record object. Comes handy when you want to use the same timestamp for
            multiple metrics.
        """
        if monitor is None:
            monitor = self.__monitor

        if monitor is None or monitor not in AgentLogger.__opened_monitors__:
            raise Exception(
                "Cannot report metric values until metric log file is opened."
            )

        if not isinstance(metric_name, _METRIC_NAME_SUPPORTED_TYPES):
            raise UnsupportedValueType(metric_name=metric_name)

        metric_name = self.force_valid_metric_or_field_name(
            metric_name, is_metric=True, logger=self
        )

        if not isinstance(metric_value, _METRIC_VALUE_SUPPORTED_TYPES):
            raise UnsupportedValueType(
                metric_name=metric_name, metric_value=metric_value
            )

        if metric_name in getattr(monitor, "_metric_name_blacklist", []):
            # NOTE: If there there tons of blacklisted metrics, this could cause log object to grow
            # because we need to store emit time for each limit key. So something to keep in mind.
            monitor_name = getattr(monitor, "raw_monitor_name", "unknown")
            limit_key = "blacklisted-metric-name-%s-%s" % (monitor_name, metric_name)

            monitor._logger.info(
                'Metric "%s" is blacklisted so the value wont be reported to Scalyr.'
                % (metric_name),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )
            return

        extra_fields_string_buffer = io.StringIO()

        if extra_fields is not None:
            # In (C)Python (2) dict keys are not sorted / ordering is not guaranteed so to ensure
            # the same order of extra fields in each log line, we explicitly sort them here
            extra_fields_names = sorted(extra_fields.keys())
            for field_name in extra_fields_names:
                if not isinstance(field_name, _METRIC_NAME_SUPPORTED_TYPES):
                    raise UnsupportedValueType(field_name=field_name)

                field_value = extra_fields[field_name]
                if not isinstance(field_value, _METRIC_VALUE_SUPPORTED_TYPES):
                    raise UnsupportedValueType(
                        field_name=field_name, field_value=field_value
                    )

                field_name = self.force_valid_metric_or_field_name(
                    field_name, is_metric=False, logger=self
                )

                extra_fields_string_buffer.write(
                    " %s=%s" % (field_name, util.json_encode(field_value))
                )

        self.info(
            "%s %s" % (metric_name, util.json_encode(metric_value))
            + extra_fields_string_buffer.getvalue(),
            metric_log_for_monitor=monitor,
            monitor_id_override=monitor_id_override,
            timestamp=timestamp,
        )
        # string_buffer.close()

        # Calculate and emit metric per second rate value (if configured and available for this
        # metric.
        # For consistency with server side, we add "_rate" suffix to the calculated rates.
        # For example: calculate_rate_metric_names -> calculate_rate_metric_names_rate
        metric_rate_value = self._calculate_metric_rate(
            monitor, metric_name, metric_value, timestamp
        )

        if metric_rate_value:
            # NOTE: We include extra_fields from the original metric, but that may not be needed
            metric_name_rate = "%s_rate" % (metric_name)
            self.info(
                "%s %s" % (metric_name_rate, util.json_encode(metric_rate_value))
                + extra_fields_string_buffer.getvalue(),
                metric_log_for_monitor=monitor,
                monitor_id_override=monitor_id_override,
                timestamp=timestamp,
            )

        extra_fields_string_buffer.close()

    def _log(
        self,
        level,
        msg,
        args,
        exc_info=None,
        extra=None,
        error_code=None,
        metric_log_for_monitor=None,
        error_for_monitor=None,
        limit_once_per_x_secs=None,
        limit_key=None,
        current_time=None,
        emit_to_metric_log=False,
        monitor_id_override=None,
        force_stdout=False,
        force_stderr=False,
        timestamp=None,
    ):
        """The central log method.  All 'info', 'warn', etc methods funnel into this method.

        New arguments (beyond inherited arguments):

        @param error_code:  The Scalyr agent error code for this record, if any.
        @param metric_log_for_monitor:  If not None, indicates the record is for a metric and the value of this
            argument is the ScalyrMonitor instance that generated it.  This is used to make sure the
            metric is recorded to the correct log.
        @param error_for_monitor:  If this is an error, then associate it with the specified monitor.  If this is
            none but this is a logger specific for a monitor instance, then that monitor's error count will
            be incremented.
        @param limit_once_per_x_secs:  If set, the logger will only emit this record if none other have been
            emitted in the last X seconds with the same key specified in the limit_key argument.  Note, this
            ignores the effects of other filters (e.g., if the record can be emitted based on the time, then it
            is recorded as being emitted even if another filter blocks it later in the chain).
        @param limit_key:  This can only be specified if limit_once_per_x_secs is not None.  It is an arbitrary string
            that uniquely identifies the set of log records that should only be emitted once per time interval.
        @param current_time:  This is only used for testing.  It sets the value to use for the current time.
        @param emit_to_metric_log:  If True, then writes the record to the metric log handler for this logger.
            This must only be used if this logger was assigned to a specific monitor.
        @param monitor_id_override:  Used to change the reported monitor id for this metric just for the purposes
            of reporting this one value.  The base monitor name will remain unchanged.
        @param force_stdout: If True, will write the log to stdout as well as the configured log file, no effect if
            the log already goes to stdout.
        @param force_stderr: If True, will write the log to stderr as well as the configured log file.
        """
        if current_time is None:
            current_time = time.time()

        if limit_once_per_x_secs is not None and limit_key is None:
            raise Exception(
                "You must specify a limit key if you specify limit_once_per_x_secs"
            )
        if limit_once_per_x_secs is None and limit_key is not None:
            raise Exception(
                "You cannot set a limit key if you did not specify limit_once_per_x_secs"
            )

        if emit_to_metric_log and self.__monitor is None:
            raise Exception(
                "You cannot set emit_to_metric_log=True on a non-monitor logger instance"
            )
        elif emit_to_metric_log:
            metric_log_for_monitor = self.__monitor

        # Make sure we limit the number of times we emit this record if it has been requested.
        if limit_once_per_x_secs is not None:
            if limit_key in self.__log_emit_times:
                last_time = self.__log_emit_times[limit_key]
                if current_time - last_time < limit_once_per_x_secs:
                    return
            self.__log_emit_times[limit_key] = current_time

        # We override the _log method so that we can accept the error_code argument.  Normally, we could
        # use extra to pass the value through to makeRecord, however, that is not available in 2.4, so we have
        # to do our own hack.  We just stick it in a thread local variable and read it out in makeRecord.
        __thread_local__.last_error_code_seen = error_code
        __thread_local__.last_metric_log_for_monitor = metric_log_for_monitor
        __thread_local__.last_monitor_id_override = monitor_id_override
        __thread_local__.last_force_stdout = force_stdout
        __thread_local__.last_force_stderr = force_stderr

        # Only associate an monitor with the error if it is in fact an error.
        if level >= logging.ERROR:
            if metric_log_for_monitor is not None:
                __thread_local__.last_error_for_monitor = error_for_monitor
            else:
                __thread_local__.last_error_for_monitor = self.__monitor
        else:
            __thread_local__.last_error_for_monitor = None

        extra = extra or {}
        # TODO / NOTE: Add support for using timestamp from "extra_fields" field for metrics
        # (if available)
        if timestamp:
            extra["timestamp"] = timestamp

        # pylint: disable=assignment-from-no-return
        if extra:
            result = logging.Logger._log(self, level, msg, args, exc_info, extra)
        elif exc_info is not None:
            result = logging.Logger._log(self, level, msg, args, exc_info)
        else:
            result = logging.Logger._log(self, level, msg, args)
        __thread_local__.last_error_code_seen = None
        __thread_local__.last_metric_log_for_monitor = None
        __thread_local__.last_error_for_monitor = None
        __thread_local__.last_monitor_id_override = None
        __thread_local__.last_force_stdout = None
        __thread_local__.last_force_stderr = None

        return result

    def makeRecord(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func=None,
        extra=None,
        # 2->TODO in python3 findCaller receives sinfo.
        sinfo=None,
    ):
        # Invoke the super class's method to make the base record.
        if extra is not None:
            result = logging.Logger.makeRecord(
                self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
            )
        elif func is not None:
            result = logging.Logger.makeRecord(
                self, name, level, fn, lno, msg, args, exc_info, func, sinfo
            )
        else:
            result = logging.Logger.makeRecord(
                self, name, level, fn, lno, msg, args, exc_info, sinfo
            )

        # Attach the special fields for the scalyr agent logging code.  These are passed from _log through a thread
        # local variable.
        result.error_code = __thread_local__.last_error_code_seen
        result.metric_log_for_monitor = __thread_local__.last_metric_log_for_monitor
        result.error_for_monitor = __thread_local__.last_error_for_monitor
        result.force_stdout = __thread_local__.last_force_stdout
        result.force_stderr = __thread_local__.last_force_stderr

        result.component = self.component
        result.monitor_name = self.monitor_name

        # Override the id as a bit of a hack.  TODO:  If there is another monitor with that id, we still only
        # update this monitor's log lines reported and error count.  We should probably increment that one.
        monitor_id_override = __thread_local__.last_monitor_id_override

        if monitor_id_override is not None:
            result.monitor_name = "%s(%s)" % (
                self.monitor_name_base,
                monitor_id_override,
            )
            result.component = "monitor:%s" % self.monitor_name

        # We also mark this record as being generated by a AgentLogger.  We use this in the root logger to
        # decide if it should be included in the agent.log output.
        result.agent_logger = True

        # If this was a metric for a particular monitor, update its records.
        if result.metric_log_for_monitor is not None:
            result.metric_log_for_monitor.increment_counter(reported_lines=1)
        if result.error_for_monitor is not None:
            result.error_for_monitor.increment_counter(errors=1)

        # If custom timestamp is provided we use that
        timestamp = getattr(result, "timestamp", None)
        if timestamp:
            timestamp_s = timestamp / 1000
            timestamp_ms = timestamp % 1000
            result.created = timestamp_s
            result.msecs = timestamp_ms

        if self.__keep_last_record:
            self.__last_record = result
        return result

    def exception(self, msg, *args, **kwargs):
        kwargs["exc_info"] = 1
        self.error(msg, *args, **kwargs)

    # The set of ScalyrMonitor instances that current have only metric logs associated with them.  This is used
    # for error checking.
    __opened_monitors__ = {}  # type: Dict[ScalyrMonitor,bool]

    def openMetricLogForMonitor(
        self,
        path,
        monitor,
        max_bytes=20 * 1024 * 1024,
        backup_count=5,
        max_write_burst=100000,
        log_write_rate=2000,
        flush_delay=0.0,
    ):
        """Open the metric log for this logger instance for the specified monitor.

        This must be called before any metrics are reported using the 'emit_value' method.  This opens the
        correct log file and prepares it to have metrics emitted to it.  Only one metric log file can be opened at
        any time per Logger instance, so any previous one is automatically closed.

        Warning, this method accesses global variables that are not thread-safe.  All calls to any logger's
        'openMetricLogForMonitor' must occur on the same thread for correctness.

        Warning, you must invoke 'closeMetricLog' to close the log file.

        @param path: The file path for the metric log file. A rotating log file will be created at this path.
        @param monitor: The ScalyrMonitor instance that will emit metrics to the log.
        @param max_bytes: The maximum number of bytes to write to the log file before it is rotated.
        @param backup_count: The number of old log files to keep around.
        @param max_write_burst: The maximum burst of bytes to allow to be written into the log. This is the bucket size
            in the "leaky bucket" algorithm.
        @param log_write_rate: The average number of bytes per second to allow to be written to the log. This is the
            bucket fill rate in the "leaky bucket" algorithm.
        @param flush_delay:  The number of seconds to wait between flushing the underlying log file.  A value of
            zero will turn off the delay.  If this is greater than zero, then some bytes might not be written to disk
            if the agent shutdowns unexpectantly.
        """
        if self.__metric_handler is not None:
            self.closeMetricLog()

        self.__metric_handler = MetricLogHandler.get_handler_for_path(
            path,
            max_bytes=int(max_bytes),
            backup_count=int(backup_count),
            max_write_burst=max_write_burst,
            log_write_rate=log_write_rate,
            flush_delay=flush_delay,
        )
        self.__metric_handler.open_for_monitor(monitor)
        self.__monitor = monitor
        AgentLogger.__opened_monitors__[monitor] = True

    def closeMetricLog(self):
        """Closes the metric log file assicated with this logger."""
        if self.__metric_handler is not None:
            self.__metric_handler.close_for_monitor(self.__monitor)
            self.__metric_handler = None
            del AgentLogger.__opened_monitors__[self.__monitor]
            self.__monitor = None

    @staticmethod
    def sanitize_metric_field_name(name):
        """
        Method which takes care of sanitizing metric field names which are considered special /
        reserved.
        """
        if not name.endswith("_") and name in RESERVED_EVENT_ATTRIBUTE_NAMES:
            name = name + "_"

        return name

    @staticmethod
    def force_valid_metric_or_field_name(name, is_metric=True, logger=None):
        """Forces the given metric or field name to be valid.

        A valid metric/field name must being with a letter or underscore and only contain alphanumeric characters including
        periods, underscores, and dashes.

        If it is not valid, it will replace invalid characters with underscores.  If it does not being with a letter
        or underscore a sa_ is added as a prefix.

        If a modification had to be applied, a log warning is emitted, but it is only emitted once per day.

        This method also ensures any "reserved" event level field names (monitor, metric, value, logfile, serverHost) are
        sanitized by adding "_" suffix (for consistency with server side parsing).

        @param name: The metric name
        @type name: six.text_type
        @param is_metric: Whether or not the name is a metric or field name
        @type is_metric: bool
        @return: The metric / field name to use, which may be the original string.
        @rtype: six.text_type
        """
        if AgentLogger.__metric_or_field_name_rule.match(name) is not None:
            name = AgentLogger.sanitize_metric_field_name(name=name)
            return name

        if is_metric and logger is not None:
            logger.warn(
                'Invalid metric name "%s" seen.  Metric names must begin with a letter and only contain '
                "alphanumeric characters as well as periods, underscores, and dashes.  The metric name has been "
                "fixed by replacing invalid characters with underscores.  Other metric names may be invalid "
                "(only reporting first occurrence)." % name,
                limit_once_per_x_secs=86400,
                limit_key="badmetricname",
                error_code="client/badMetricName",
            )
        elif logger is not None:
            logger.warn(
                'Invalid field name "%s" seen.  Field names must begin with a letter and only contain '
                "alphanumeric characters as well as periods, underscores, and dashes.  The field name has been "
                "fixed by replacing invalid characters with underscores.  Other field names may be invalid "
                "(only reporting first occurrence)." % name,
                limit_once_per_x_secs=86400,
                limit_key="badfieldname",
                error_code="client/badFieldName",
            )

        if not re.match(r"^[_a-zA-Z]", name):
            name = "sa_" + name

        name = AgentLogger.sanitize_metric_field_name(name=name)
        return re.sub(r"[^\w\-\.]", "_", name)

    def report_values(self, values, monitor=None):
        """Records the specified values (a dict) to the underlying log.

        NOTE:  This is being deprecated in favor of emit_value.

        This may only be called after the metric file for the monitor has been opened.

        @param values: A dict containing a mapping from metric name to its value. The only allowed value types are:
            int, long, float, bool, and six.text_type.
        @param monitor: The ScalyrMonitor instance that created the values. This does not have to be passed in if the
            monitor instance specific logger is used. It defaults to that monitor. However, if the logger is the
            general one for the module, then a monitor instance is required.

            UnsupportedValueType if the value type is not one of the supported types.
        """
        self.emit_values(values, monitor=monitor)

    def emit_values(self, values, monitor=None):
        """Records the specified values (a dict) to the underlying log.

        NOTE:  This is being deprecated in favor of emit_value.

        This may only be called after the metric file for the monitor has been opened.

        @param values: A dict containing a mapping from metric name to its value. The only allowed value types are:
            int, long, float, bool, and six.text_type.
        @param monitor: The ScalyrMonitor instance that created the values. This does not have to be passed in if the
            monitor instance specific logger is used. It defaults to that monitor. However, if the logger is the
            general one for the module, then a monitor instance is required.

            UnsupportedValueType if the value type is not one of the supported types.
        """
        if monitor is None:
            monitor = self.__monitor

        if monitor is None or monitor not in AgentLogger.__opened_monitors__:
            raise Exception(
                "Cannot report metric values until metric log file is opened."
            )

        string_entries = []
        for key in values:
            value = values[key]
            value_type = type(value)
            if value_type in six.integer_types or value_type is float:
                string_entries.append("%s=%s" % (key, six.text_type(value)))
            elif value_type is bool:
                value_str = "true"
                if not value:
                    value_str = "false"
                string_entries.append("%s=%s" % (key, value_str))
            elif value_type is six.text_type:
                string_entries.append(
                    "%s=%s" % (key, six.text_type(value).replace('"', '\\"'))
                )
            else:
                raise UnsupportedValueType(key, value)
        self.info(" ".join(string_entries), metric_log_for_monitor=monitor)

    # 2->TODO in python3 findCaller receives stack_info, Also there is a new 'stacklevel' in python3.8
    def findCaller(self, stack_info=False, stacklevel=1):
        """
        Find the stack frame of the caller so that we can note the source
        file name, line number and function name.
        """
        f = currentframe()
        # On some versions of IronPython, currentframe() returns None if
        # IronPython isn't run with -X:Frames.
        if f is not None:
            f = f.f_back
        rv = "(unknown file)", 0, "(unknown function)"
        while hasattr(f, "f_code"):
            co = f.f_code
            filename = os.path.normpath(os.path.normcase(co.co_filename))
            # noinspection PyProtectedMember
            if filename == _srcfile or filename == logging._srcfile:
                f = f.f_back
                continue
            rv = (co.co_filename, f.f_lineno, co.co_name, None)
            break

        if sys.version_info[0] == 2:
            # Python 2.
            return rv[:3]
        else:
            # Python 3.
            return rv

    @property
    def last_record(self):
        return self.__last_record

    def set_keep_last_record(self, keep_last):
        """Updates whether or not to keep the last record created by this logger.

        :param keep_last: Whether or not to keep the last record
        :type keep_last: bool
        """
        if keep_last != self.__keep_last_record:
            self.__last_record = None

        self.__keep_last_record = keep_last


# To help with a hack of extending the Logger class, we need a thread local storage
# to store the last error status code and metric information seen by this thread.
__thread_local__ = threading.local()


class BaseFormatter(logging.Formatter):
    """Commom formatter base class used by the Scalyr log formatters.

    This base class provides some common functionality to be used in conjunction with the RateLimiterFilter.
    Specifically, it caches the result of the format operation so that multiple calls do not result in reformatting.
    Also, it appends a warning message when records were dropped due to rate limiting.
    """

    def __init__(self, fmt, format_name):
        """Creates an instance of the formatter.

        @param fmt: The format string to use for the format.
        @param format_name: A name that is unique to the derived format class. This is used to make sure different
            format results are cached under different keys.
        """
        self.__cache_key = "cached_format_%s" % format_name
        logging.Formatter.__init__(self, fmt=fmt)

    def format(self, record):
        # Check to see if there is a cached result already for this format.
        if hasattr(record, self.__cache_key):
            return getattr(record, self.__cache_key)

        # Otherwise, build the format.  Prepend a warning if we had to skip lines.
        if getattr(record, "rate_limited_dropped_records", 0) > 0:
            result = (
                ".... Warning, skipped writing %ld log lines due to limit set by `%s` option...\n%s"
                % (
                    record.rate_limited_dropped_records,
                    "monitor_log_write_rate",
                    logging.Formatter.format(self, record),
                )
            )
        else:
            result = logging.Formatter.format(self, record)

        setattr(record, self.__cache_key, result)
        return result

    def formatTime(self, record, datefmt=None):
        # We define our own custom time format in order to use a period for separate seconds from milliseconds.
        # Yes, the comma annoys us -- most other Scalyr logs used a period.
        ct = time.gmtime(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
            s = "%s.%03dZ" % (t, record.msecs)
        return s


class AgentLogFormatter(BaseFormatter):
    """Formatter used for the logs produced by the agent both for diagnostic information.

    In general, it formats each line as:
        time (with milliseconds)
        levelname (DEBUG, INFO, etc)
        component (which component of the agent produced the problem such as 'core' or a monitor.)
        line (file name and line number that produced the log message)
        error (the error code)
        message (the logged message)
    """

    def __init__(self):
        # TODO: It seems on Python 2.4 the filename and line number do not work correctly.  I think we need to
        # define a custom findCaller method to actually fix the problem.
        BaseFormatter.__init__(
            self,
            "%(asctime)s %(levelname)s [%(component)s] [%(filename)s:%(lineno)d] "
            "%(error_message)s%(message)s%(stack_token)s",
            "agent_formatter",
        )

    def format(self, record):
        # Optionally add in the error code if there is one present.
        if record.error_code is not None:
            record.error_message = '[error="%s"] ' % record.error_code
        else:
            record.error_message = ""

        if record.exc_info:
            record.stack_token = " :stack_trace:"
        else:
            record.stack_token = ""
        return BaseFormatter.format(self, record)

    def formatException(self, ei):
        # We just want to indent the stack trace to make it easier to write a parsing rule to detect it.
        output = io.StringIO()
        try:
            # 2->TODO 'logging.Formatter.formatException' returns binary data (str) in python2,
            #  so it will not work with io.StringIO here.
            exception_string = six.ensure_text(
                logging.Formatter.formatException(self, ei)
            )

            for line in exception_string.splitlines(True):
                output.write("  ")
                output.write(line)
            return output.getvalue()
        finally:
            output.close()


class MetricLogFormatter(BaseFormatter):
    """Formatter used for the logs produced by the agent both for metric reporting.

    In general, it formats each line as:
        time (with milliseconds)
        component (which component of the agent produced the problem such as 'core' or a monitor.)
        message (the logged message)
    """

    def __init__(self):
        BaseFormatter.__init__(
            self, "%(asctime)s [%(monitor_name)s] %(message)s", "metric-formatter"
        )


class AgentLogFilter(object):
    """A filter that includes any record emitted by an AgentLogger instance unless it was a metric record.

    Also will filter records with logging.DEBUG and lower if this filter is not meant for a debug handler,
    and greater than logging.DEBUG if it is.
    """

    def __init__(self, is_debug):
        """Initializes the filter.

        @param is_debug: If True, then will only pass records that have a level of logging.DEBUG or lower.  If False,
            then will only pass records that have a level greater than logging.DEBUG.  This allows us to create
            separate log files for debug and non-debug records
        @type is_debug: bool
        """
        self.__is_debug = is_debug

    def filter(self, record):
        """Performs the filtering.

        @param record: The record to filter.
        @type record: logging.LogRecord

        @return:  True if the record should be logged by this handler.
        @rtype: bool
        """
        if self.__is_debug and record.levelno > logging.DEBUG:
            return False
        elif not self.__is_debug and record.levelno <= logging.DEBUG:
            return False

        return (
            getattr(record, "agent_logger", False)
            and record.metric_log_for_monitor is None
        )


class RateLimiterLogFilter(object):
    """A filter that rejects records when a maximum write rate has been exceeded, as calculated by
    a leaky bucket algorithm."""

    def __init__(self, formatter, max_write_burst=100000, log_write_rate=2000):
        """Creates an instance.

        @param formatter: The formatter instance used by the Logger to generate the string used to represent a
            particular record. This is used to determine how many bytes the record will consume. This should be derived
            from BaseFormatter since it has some features to make sure we do not serialize the record twice.
        @param max_write_burst: The maximum burst of bytes to allow to be written into the log. This is the bucket size
            in the "leaky bucket" algorithm.
        @param log_write_rate: The average number of bytes per second to allow to be written to the log. This is the
            bucket fill rate in the "leaky bucket" algorithm.

        @return:"""
        self.__rate_limiter = RateLimiter(
            bucket_size=max_write_burst, bucket_fill_rate=log_write_rate
        )
        self.__dropped_records = 0
        self.__formatter = formatter

    def filter(self, record):
        if hasattr(record, "rate_limited_set"):
            return record.rate_limited_result

        record.rate_limited_set = True
        # Note, it is important we set rate_limited_dropped_records before we invoke the formatter since the
        # formatting is dependent on that value and our formatters cache the result.
        record.rate_limited_dropped_records = self.__dropped_records
        record_str = self.__formatter.format(record)

        # Store size of the original and formatted records on the record object itself. Right now
        # this is mostly used in the tests, but could also be useful in other contexts.
        record.original_size = len(record.message)
        record.formatted_size = len(record_str)
        record.rate_limited_result = self.__rate_limiter.charge_if_available(
            len(record_str)
        )

        if record.rate_limited_result:
            self.__dropped_records = 0
            return True
        else:
            self.__dropped_records += 1
            return False


class StdoutFilter(object):
    """A filter for outputting logs to stdout.
    Will output the record if `no_fork` is true and the record has a severity of `stdout_severity` or higher.
    Alternatively if `force_stdout` is true in the record it will always be output to stdout.
    """

    def __init__(self, no_fork, stdout_severity):
        """Initializes the filter."""
        self.__no_fork = no_fork

        self.__stdout_severity = logging.getLevelName(stdout_severity.upper())

        if not isinstance(self.__stdout_severity, int):
            # If getLevelName() returns a string this means a level with the provided name doesn't
            # exist so we fall back to notset
            self.__stdout_severity = 0

    def filter(self, record):
        """Performs the filtering.

        We have a partial copy of the filtering done in AgentLogFilter in this one, because we want the same filtering
        as a normal agent log, but without the separation into debug and non-debug files.

        @param record: The record to filter.
        @type record: logging.LogRecord

        @return:  True if the record should be logged by this handler.
        @rtype: bool
        """
        # TODO: We don't handle our custom debug log levels correctly.
        # If DEBUG level is specified we should use level number 5 since that
        # represents the lowest number for the custom debug log level we define
        return getattr(record, "force_stdout", False) or (
            self.__no_fork
            and record.levelno >= self.__stdout_severity
            and getattr(record, "agent_logger", False)
            and record.metric_log_for_monitor is None
        )


class StderrFilter(object):
    """A filter that includes any record if it has `force_stderr` as True"""

    def __init__(self):
        """Initializes the filter."""

    def filter(self, record):
        """Performs the filtering.

        @param record: The record to filter.
        @type record: logging.LogRecord

        @return:  True if the record should be logged by this handler.
        @rtype: bool
        """
        return getattr(record, "force_stderr", False)


class MetricLogHandler(object):
    """The LogHandler to use for recording metric values emitted by Scalyr agent monitors.

    The handler has several features such as a way to guarantee there is only one handler instance for each metric
    log file being used, tracking the Scalyr monitor instances associated with it, etc.

    This is a base class that is used below to implement different versions of the MetricLogHandler that either
    uses a rotating log file or writes to stdout.
    """

    def __init__(self, file_path, max_write_burst=10000, log_write_rate=2000):
        """Creates the handler instance.  This should not be used directly.  Use MetricLogHandler.get_handler_for_path
        instead.

        @param max_write_burst: The maximum burst of bytes to allow to be written into the log. This is the bucket size
            in the "leaky bucket" algorithm.
        @param log_write_rate: The average number of bytes per second to allow to be written to the log. This is the
            bucket fill rate in the "leaky bucket" algorithm.
        """
        # The monitor instances that should emit their metrics to this log file.
        self.__monitors = {}
        # True if this handler has been added to the root logger.  To allow for multiple different modules and
        # Scalyr monitors to emit to the same metric file, we do not place this handler in each of the loggers for
        # those modules, but instead put one instance on the root logger and just filter it to emit only those metrics
        # for the monitors in self.__monitors.
        self.__added_to_root = False
        self.__file_path = file_path

        class Filter(object):
            """The filter used by the MetricLogHandler that only returns true if the record is for a metric for one of
            the monitors associated with the metric log file.
            """

            def __init__(self, allowed_monitors):
                self.__monitors = allowed_monitors

            def filter(self, record):
                return (
                    getattr(record, "metric_log_for_monitor", None) in self.__monitors
                )

        # Add the filter and our formatter to this handler.
        self.addFilter(Filter(self.__monitors))
        formatter = MetricLogFormatter()
        if max_write_burst >= 0 and log_write_rate >= 0:
            self.addFilter(
                RateLimiterLogFilter(
                    formatter,
                    max_write_burst=max_write_burst,
                    log_write_rate=log_write_rate,
                )
            )
        self.setFormatter(formatter)

    # noinspection PyPep8Naming
    def addFilter(self, _):
        """Adds the filter to the underlying logging.Handler."""
        # This is actually overridden by the derived class.  We keep this here to override lint warnings from
        # the constructor's use of the method.
        pass

    # noinspection PyPep8Naming
    def setFormatter(self, _):
        """Sets the formatter for the underlying logging.Handler."""
        # This is actually overridden by the derived class.  We keep this here to override lint warnings from
        # the constructor's use of the method.
        pass

    def close(self):
        """Closes the underlying logging.Handler."""
        # This is actually overridden by the derived class.  We keep this here to override lint warnings from
        # the constructor's use of the method.
        pass

    # Static variable that maps file paths to the handlers responsible for them.
    __metric_log_handlers__ = {}  # type: Dict[str, MetricLogHandler]

    # Static variable that determines if all metric output will be written to stdout instead of the normal
    # metric log file.
    __use_stdout__ = False

    @staticmethod
    def set_use_stdout(use_stdout):
        """Sets whether or not all emitted metric values will be sent to stdout instead of the normal log files.

        This is used for testing and debugging.

        @param use_stdout: True if all metric values should be written to stdout.
        """
        MetricLogHandler.__use_stdout__ = use_stdout

    @staticmethod
    def get_handler_for_path(
        file_path,
        max_bytes=20 * 1024 * 1024,
        backup_count=5,
        max_write_burst=100000,
        log_write_rate=2000,
        flush_delay=0.0,
    ):
        """Returns the MetricLogHandler to use for the specified file path.  This must be used to get
        MetricLogHandler instances.

        This method is not thread-safe so all calls to getHandlerPath must be issued from the same thread.

        Note, open_for_monitor must be invoked in order to allow a particular monitor to emit metric values to this
        log.

        This method either returns a handler that writes to the specified path with a rotating log file, or to
        stdout, if set_metric_log_destination has been invoked.

        @param file_path: The file path for the metric log file.
        @param max_bytes: The maximum number of bytes to write to the log file before it is rotated.
        @param backup_count: The number of previous log files to keep.
        @param max_write_burst: The maximum burst of bytes to allow to be written into the log. This is the bucket size
            in the "leaky bucket" algorithm.
        @param log_write_rate: The average number of bytes per second to allow to be written to the log. This is the
            bucket fill rate in the "leaky bucket" algorithm.
        @param flush_delay:  The number of seconds to wait before flushing the underlying file handle after a line
            has been written to the log file.  You may supply 0.0 to always flush.  This only applies to the log
            file when it is being written to a physical log and not when it is written to stdout.

        @return: The handler instance to use.
        """
        if file_path not in MetricLogHandler.__metric_log_handlers__:
            if not MetricLogHandler.__use_stdout__:
                result = MetricRotatingLogHandler(
                    file_path,
                    max_bytes=int(max_bytes),
                    backup_count=int(backup_count),
                    max_write_burst=max_write_burst,
                    log_write_rate=log_write_rate,
                    flush_delay=flush_delay,
                )
            else:
                result = MetricStdoutLogHandler(
                    file_path,
                    max_write_burst=max_write_burst,
                    log_write_rate=log_write_rate,
                )
            MetricLogHandler.__metric_log_handlers__[file_path] = result
        return MetricLogHandler.__metric_log_handlers__[file_path]

    def open_for_monitor(self, monitor):
        """Configures this instance to allow the specified monitor to emit its metrics to it.

        This method is not thread-safe.

        @param monitor: The monitor instance that should emit its values to the log file handled by this instance.
        """
        # In order to support multiple modules using the same log file to record their metrics, we add this
        # handler to the root logger and then just use a filter to decide which metrics to emit once they propogate
        # up to the root.
        if not self.__added_to_root:
            logging.getLogger().addHandler(self)
            self.__added_to_root = True

        self.__monitors[monitor] = True

    def close_for_monitor(self, monitor):
        """Configures this instance to no longer log metrics for the specified monitor instance.

        If this is the last monitor that was being handled by this instance, then the underlying log file will
        be closed.

        This method is not thread safe.

        @param monitor: The monitor instance.
        """
        if monitor in self.__monitors:
            del self.__monitors[monitor]

        # If this handler no longer has any monitors, then it is no longer needed and we should close/remove it.
        if len(self.__monitors) == 0:
            if self.__added_to_root:
                logging.getLogger().removeHandler(self)

            self.close()

            del MetricLogHandler.__metric_log_handlers__[self.__file_path]


class AutoFlushingRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    An extension to the RotatingFileHandler for logging that does not flush after every line is emitted.
    Instead, it is guaranteed to flush once every ``flushDelay`` seconds.

    This helps reduce the disk requests for high syslog traffic.
    """

    def __init__(
        self, filename, mode="a", maxBytes=0, backupCount=0, delay=0, flushDelay=0.0
    ):
        # We handle delay specially because it is not a valid option for the Python 2.4 logging libraries, so we
        # really only pass it if the caller is really trying to set it to something other than the default.
        if delay != 0:
            logging.handlers.RotatingFileHandler.__init__(
                self,
                filename,
                mode=mode,
                maxBytes=maxBytes,
                backupCount=backupCount,
                delay=delay,
            )
        else:
            logging.handlers.RotatingFileHandler.__init__(
                self, filename, mode=mode, maxBytes=maxBytes, backupCount=backupCount
            )

        self.__flushDelay = flushDelay
        # If this is not None, then it is set to a timer that when it expires will flush the log handler.
        # You must hold the I/O lock in order to set/manipulate this variable.
        self.__timer = None

    def set_flush_delay(self, flushDelay):
        """Sets the flush delay.

        Warning, this method is not thread safe.  You should invoke it soon after the constructor and before the
        handler is actually in use.

        @param flushDelay: The maximum number of seconds to wait to flush the underlying file handle.
        @type flushDelay: float
        @return:
        @rtype:
        """
        self.__flushDelay = flushDelay

    def flush(self):
        if self.__flushDelay == 0:
            self._internal_flush()
        else:
            self.acquire()
            try:
                if self.__timer is None:
                    self.__timer = threading.Timer(
                        self.__flushDelay, self._internal_flush
                    )
                    self.__timer.start()
            finally:
                self.release()

    def close(self):
        if self.__flushDelay > 0:
            self.acquire()
            self.__flushDelay = 0
            try:
                if self.__timer is not None:
                    self.__timer.cancel()
                    self.__timer = None
            finally:
                self.release()
        logging.handlers.RotatingFileHandler.close(self)

    def _internal_flush(self):
        logging.handlers.RotatingFileHandler.flush(self)
        if self.__flushDelay > 0:
            self.acquire()
            try:
                if self.__timer is not None:
                    self.__timer.cancel()
                    self.__timer = None
            finally:
                self.release()


class MetricRotatingLogHandler(AutoFlushingRotatingFileHandler, MetricLogHandler):
    def __init__(
        self,
        file_path,
        max_bytes,
        backup_count,
        max_write_burst=100000,
        log_write_rate=2000,
        flush_delay=0.0,
    ):
        AutoFlushingRotatingFileHandler.__init__(
            self,
            file_path,
            maxBytes=int(max_bytes),
            backupCount=int(backup_count),
            flushDelay=flush_delay,
        )
        MetricLogHandler.__init__(
            self,
            file_path,
            max_write_burst=max_write_burst,
            log_write_rate=log_write_rate,
        )
        self.propagate = False


class MetricStdoutLogHandler(logging.StreamHandler, MetricLogHandler):
    def __init__(self, file_path, max_write_burst=100000, log_write_rate=2000):
        logging.StreamHandler.__init__(self, WrapStdout())
        MetricLogHandler.__init__(
            self,
            file_path,
            max_write_burst=max_write_burst,
            log_write_rate=log_write_rate,
        )
        self.propagate = False


class WrapStdout(object):
    """A stream implementation that sends all operations to `sys.stdout`.

    This is useful for creating a StreamHandler that will write to this object, but actually end up sending all
    output to `sys.stdout`.  Even if the `sys.stdout` object changes while the handler is active, it will still
    go to the most up-to-date `sys.stdout` value.  This is useful when we do change where `stdout` is going, such
    as on the Windows redirect.
    """

    def flush(self):
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()

    def write(self, content):
        if hasattr(sys.stdout, "write"):
            sys.stdout.write(content)

    def close(self):
        if hasattr(sys.stdout, "close"):
            sys.stdout.close()


class AgentLogManager(object):
    """The central manager for all AgentLoggers.

    There is only one instance of this object created per running process.  It is meant to hold the global-like
    variables necessary to coordinate using single handlers for all the logger instances, as well as setting
    a global log level on all AgentLogger instances.
    """

    def __init__(self):
        # The file names for the main and debug log.  The main log is usually 'agent.log' and contains all the
        # non-debug level log records created by the AgentLogger instances.  This log is typically copied to
        # Scalyr.
        self.__main_log_fn = None
        # The debug log is the log we only create when debug logging is turned on and usually has the name
        # 'agent_debug.log'.  It contains all debug level records created by the AgentLogger instances.  This
        # log will grow large and is not meant to be sent to Scalyr.
        self.__debug_log_fn = None

        # The current logging.Handler objects that will handle all records intended for the main and debug logs.
        # These handlers are with ones that write to stdout or to a rotating log file with the appropriate name.
        self.__main_log_handler = None
        self.__debug_log_handler = None

        # logging.Handler objects for use when logging with `force_stdout` or `force_stderr` enabled.
        # These handlers have a filter on them to only log when the relevant parameter is True.
        self.__force_stdout_handler = None
        self.__force_stderr_handler = None

        # If True, then logging will be sent to stdout rather than the file names mentioned above.
        self.__use_stdout = True

        # If True we are running unforked and should log things to stdout as well as the log file, messages with
        # severity greater than or equal to `self.__stdout_severity` will be logged to stdout.
        self.__no_fork = False
        self.__stdout_severity = "NOTSET"

        # If using a rotating log, this is the maximum number of bytes that can be written before it is rotated.
        self.__rotation_max_bytes = 20 * 1024 * 1024
        # The number of previous logs that will be kept from the rotation.
        self.__rotation_backup_count = 2

        # For the main log, the average write rate that is allowed for the log file.  This is meant to guard against
        # the agent.log producing way too much information by a rogue bug or monitor and therefore use up a good portion
        # of the customer's allowed log upload rate.
        self.__log_write_rate = 2000
        # The maximum burst rate that is allowed to the main log file (using a leaky bucket algorithm to rate limit
        # the writes).
        self.__max_write_burst = 1000000

        # A lock to protected the __logger, __log_level, and __is_debug_on variables.
        self.__lock = threading.Lock()

        # The global logging level to use for all AgentLogger instances.
        self.__log_level = logging.INFO

        # Whether or not the log level is set to a debug log level.
        self.__is_debug_on = False

        # The list of all logger instances created so far.  Since loggers can be created by other threads,
        # this needs to be thread safe.  It might seem bad to keep a reference to the instances since they will
        # never be garbage collected, but the logging classes already do that to implement features like getLogger.
        self.__loggers = []

    def set_log_destination(
        self,
        use_stdout=False,
        use_disk=False,
        no_fork=False,
        stdout_severity="NOTSET",
        logs_directory=None,
        agent_log_file_path="agent.log",
        agent_debug_log_file_suffix="_debug",
        max_bytes=20 * 1024 * 1024,
        backup_count=2,
        log_write_rate=2000,
        max_write_burst=100000,
    ):
        """For documentation, see the scalyr_logging.set_log_destination method."""
        if use_stdout and use_disk:
            raise Exception("You cannot specify both use_disk and use_stdout")
        elif not use_stdout and not use_disk:
            raise Exception("You must specify at least one of use_stdout or use_diskk.")

        self.__use_stdout = use_stdout
        self.__no_fork = no_fork
        self.__stdout_severity = stdout_severity
        self.__rotation_max_bytes = int(max_bytes)
        self.__rotation_backup_count = int(backup_count)
        self.__log_write_rate = log_write_rate
        self.__max_write_burst = max_write_burst

        # We only update the file paths if we are going to be using the disk.
        if use_disk:
            self.__main_log_fn = self.__create_main_log_path(
                agent_log_file_path, logs_directory
            )
            self.__debug_log_fn = self.__create_debug_log_path(
                self.__main_log_fn, agent_debug_log_file_suffix
            )

        self.__recreate_main_handler()
        self.__recreate_debug_handler()
        self.__recreate_force_stdout_handler()
        self.__recreate_force_stderr_handler()
        self.__reset_root_logger()
        MetricLogHandler.set_use_stdout(use_stdout)

    def add_logger_instance(self, new_instance):
        """Adds a new instance of an AgentLogger to the manager.

        This method will also set the log level of the new instance to the correct level.
        This method is thread safe.

        @param new_instance: The new instance.
        @type new_instance: AgentLogger
        """
        self.__lock.acquire()
        try:
            self.__loggers.append(new_instance)
            new_instance.setLevel(self.__log_level)
        finally:
            self.__lock.release()

    def set_log_level(self, level):
        """Sets the log level that should be used by all AgentLogger instances.

        This method is thread safe.

        @param level: The level, in the logging units by the logging package, such as logging.INFO, logging.DEBUG, etc.
            You can also use one of the Scalyr debug levels, such as DEBUG_LEVEL_0, DEBUG_LEVEL_1, etc.
        @type level: int
        """
        self.__lock.acquire()
        try:
            if self.__log_level == level:
                return

            self.__log_level = level
            self.__is_debug_on = level <= logging.DEBUG
            # Have to go set the levels on all the created instances.  We do not acquire the lock here since this
            # method is already known to be not thread safe and can only be called from the main thread.
            for logger in self.__loggers:
                logger.setLevel(level)

            # Since this might have changed __is_debug_on and therefore whether or not we should have a debug log
            # handler, we need to recreate it.  We also need to hold the lock while we do this since it will
            # read the value of __is_debug_on.
            self.__recreate_debug_handler()
            self.__recreate_force_stdout_handler()
            self.__recreate_force_stderr_handler()
            self.__reset_root_logger()
        finally:
            self.__lock.release()

    def set_log_level_for_loggers(self, loggers, level):
        """
        Set log level for the provided loggers.

        This method is mostly to be used in scenarios where we set debug level for a subset of loggers
        (e.g. single or multiple monitor modules).
        """
        self.__lock.acquire()

        try:
            for logger in loggers:
                logger.setLevel(level)

            self.__recreate_debug_handler(force=True)
            self.__reset_root_logger()
        finally:
            self.__lock.release()

    @property
    def log_level(self):
        """
        @return:  The log level that should be used by all AgentLoggers.
        @rtype: int
        """
        self.__lock.acquire()
        try:
            return self.__log_level
        finally:
            self.__lock.release()

    def __recreate_main_handler(self):
        """Recreates the main log handler according to the variables set on this instance.

        If there is already a main handler, this method will close it.

        If self.__stdout is set, then a handler will be created for stdout, otherwise it is a rotating log handler
        for to the self.__main_log_fn file name.

        You must invoke `__reset_root_logger` at some point after this call for it to take effect.
        """
        self.__main_log_handler = self.__recreate_handler(
            self.__main_log_fn, is_debug=False
        )

    def __recreate_debug_handler(self, force=False):
        """Recreates the debug log handler according to the variables set on this instance.

        If there is already a debug log handler, this method will close it.

        If a debug level is not set, then this will not create a handler.

        If self.__stdout is set, then a handler will be created for stdout, otherwise it is a rotating log handler
        for to the self.__main_log_fn file name.

        Note, you should hold __lock if this is being called from a method that needs to be thread safe.

        You must invoke `__reset_root_logger` at some point after this call for it to take effect.

        :param force: True to force recreate the debug handler. This should be set to True when
                      setting debug log level for a single or subset of all the loggers.
        """
        self.__debug_log_handler = self.__recreate_handler(
            self.__debug_log_fn,
            is_debug=True,
            is_force_debug=force,
        )

    def __recreate_force_stdout_handler(self):
        """Recreates the stdout log handler according to the variables set on this instance.

        If self.__stdout is set, then the handler will be set to `None` to avoid duplicate logs to stdout, otherwise
        it will be the same logger as a main handler with self.__stdout set to True.

        You must invoke `__reset_root_logger` at some point after this call for it to take effect.
        """
        self.__force_stdout_handler = self.__recreate_handler(
            self.__main_log_fn, is_force_stdout=True
        )

    def __recreate_force_stderr_handler(self):
        """Recreates the stderr log handler according to the variables set on this instance.

        You must invoke `__reset_root_logger` at some point after this call for it to take effect.
        """
        self.__force_stderr_handler = self.__recreate_handler(
            self.__main_log_fn, is_force_stderr=True
        )

    def __recreate_handler(
        self,
        file_path,
        is_debug=False,
        is_force_debug=False,
        is_force_stdout=False,
        is_force_stderr=False,
    ):
        """Creates and returns an appropriate handler for either the main, debug, forced stdout, or force stderr log.

        @param file_path: The file name for the log file.  This is only used if the logger should not be writing to
            stdout (as determined by self.__use_stdout).
        @param is_debug: True if this handler is for the debug log.

        @type file_path: str
        @type is_debug: bool

        @return: The created handler or None if none should be created.
        @rtype: logging.LogHandler
        """
        if is_debug and not is_force_debug and not self.__is_debug_on:
            return None
        if self.__use_stdout and is_force_stdout:
            return None

        # Create the right type of handler.
        if is_force_stdout:
            handler = logging.StreamHandler(sys.stdout)
            handler.addFilter(StdoutFilter(self.__no_fork, self.__stdout_severity))
        elif is_force_stderr:
            handler = logging.StreamHandler(sys.stderr)
            handler.addFilter(StderrFilter())
        elif self.__use_stdout:
            handler = logging.StreamHandler(sys.stdout)
        else:
            handler = logging.handlers.RotatingFileHandler(
                file_path,
                maxBytes=self.__rotation_max_bytes,
                backupCount=self.__rotation_backup_count,
            )

        handler.addFilter(AgentLogFilter(is_debug))

        formatter = AgentLogFormatter()
        # Rate limit the log if this is the main log since we are copying it up to Scalyr as well.
        if not is_debug:
            handler.addFilter(
                RateLimiterLogFilter(
                    formatter,
                    max_write_burst=self.__max_write_burst,
                    log_write_rate=self.__log_write_rate,
                )
            )
        handler.setFormatter(formatter)
        return handler

    def __reset_root_logger(self):
        """Reset the handlers on the root logger to be only the handlers we want.

        This must be invoked whenever you rebuild either the `__main_log_handler`, `__debug_log_handler`,
        `__force_stdout_handler`, or `__force_stderr_handler`.
        """
        # Because we gather logs from all modules, we add our handlers to the top most Logger.  The records will
        # propagate up there and then we will write them to disk or stdout.
        root_logger = logging.getLogger()

        # We remove all other handlers on the root.  We are forcing the system to only use what we want.
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            if handler:
                # Don't call close on None in case __recreate_handler returns None
                handler.close()

        root_logger.addHandler(self.__main_log_handler)
        if self.__force_stdout_handler:
            root_logger.addHandler(self.__force_stdout_handler)
        root_logger.addHandler(self.__force_stderr_handler)
        if self.__debug_log_handler is not None:
            root_logger.addHandler(self.__debug_log_handler)

    def __create_main_log_path(self, agent_log_file_path, logs_directory):
        """Creates and returns the file name to use for the main log.

        @param agent_log_file_path: The agent file path as specified by the configuration.  This is either a file name
            or a full path.
        @param logs_directory: The path to the log directory.  If the agent_log_file_path is relative, it is
            resolved against this directory.

        @type agent_log_file_path: str
        @type logs_directory: str

        @return:  The full file path for the main log file.
        @rtype: str
        """
        if not os.path.isabs(agent_log_file_path):
            return os.path.realpath(os.path.join(logs_directory, agent_log_file_path))
        else:
            return os.path.realpath(agent_log_file_path)

    def __create_debug_log_path(self, agent_log, agent_debug_log_file_suffix):
        """Creates and returns the file name to use for the debug log log.

        This file path will be based directly on the main log file name.  Generally, we find the first '.' in the
        file name portion of the main log file, and insert the suffix right before it.  So, 'agent.log' becomes
        'agent_debug.log'.

        If there is no period, then we just add the suffix to the end.

        @param agent_log:  The full file path of the main log file.
        @param agent_debug_log_file_suffix:  The suffix to insert before the first period, or to the end of the
            main file name.

        @type agent_log: str
        @type agent_debug_log_file_suffix: str

        @return:  The full file path for the debug log file.
        @rtype: str
        """
        dir_name = os.path.dirname(agent_log)
        file_name = os.path.basename(agent_log)
        if "." in file_name:
            index_of_first = file_name.find(".")
            return os.path.join(
                dir_name,
                "%s%s.%s"
                % (
                    file_name[0:index_of_first],
                    agent_debug_log_file_suffix,
                    file_name[index_of_first + 1 :],
                ),
            )
        else:
            return "%s%s" % (agent_log, agent_debug_log_file_suffix)


# noinspection PyRedeclaration
__log_manager__ = AgentLogManager()


class BadMetricOrFieldName(Exception):
    """Exception raised when a metric or field name used to report a metric value is invalid."""

    def __init__(self, metric_or_field_name):
        Exception.__init__(
            self,
            'A bad metric or field name of "%s" was seen when reporting metrics.  '
            "It must begin with a letter and only contain alphanumeric characters as well as periods,"
            "underscores, and dashes." % metric_or_field_name,
        )


# A sentinel value used to indicate an argument was not specified.  We do not use None to indicate
# NOT_GIVEN since the argument's value may be None.
__NOT_GIVEN__ = {}  # type: ignore


class UnsupportedValueType(Exception):
    """Exception raised when an MetricValueLogger is asked to emit a metric with an unsupported type."""

    def __init__(
        self,
        metric_name=__NOT_GIVEN__,
        metric_value=__NOT_GIVEN__,
        field_name=__NOT_GIVEN__,
        field_value=__NOT_GIVEN__,
    ):
        """Constructs an exception.

        There are several different modes of operation for this exception.  If only metric_name or field_name
        are given, then the error message will indicate the name is bad because it is not str or unicode.
        If a metric_name and metric_value are given, then the value is assumed to be a bad type and an
        appropriate error message is generated.  Same with field_name and field_value.
        """
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.field_name = field_name
        self.field_value = field_value

        if metric_name is not __NOT_GIVEN__ and metric_value is __NOT_GIVEN__:
            message = (
                "An unsupported type for a metric name was given.  It must be either str or unicode, but was "
                '"%s".  This was for metric "%s"'
                % (six.text_type(type(metric_name)), six.text_type(metric_name))
            )
        elif field_name is not __NOT_GIVEN__ and field_value is __NOT_GIVEN__:
            message = (
                "An unsupported type for a field name was given.  It must be either str or unicode, but was "
                '"%s".  This was for field "%s"'
                % (six.text_type(type(field_name)), six.text_type(field_name))
            )
        elif metric_name is not __NOT_GIVEN__ and metric_value is not __NOT_GIVEN__:
            message = (
                'Unsupported metric value type of "%s" with value "%s" for metric="%s". '
                "Only int, long, float, and str are supported."
                % (
                    six.text_type(type(metric_value)),
                    six.text_type(metric_value),
                    metric_name,
                )
            )
        elif field_name is not __NOT_GIVEN__ and field_value is not __NOT_GIVEN__:
            message = (
                'Unsupported field value type of "%s" with value "%s" for field="%s". '
                "Only int, long, float, and str are supported."
                % (
                    six.text_type(type(field_value)),
                    six.text_type(field_value),
                    field_name,
                )
            )
        else:
            raise Exception(
                'Bad combination of fields given for UnsupportedValueType: "%s" "%s" "%s" "%s"'
                % (
                    six.text_type(metric_name),
                    six.text_type(metric_value),
                    six.text_type(field_name),
                    six.text_type(field_value),
                )
            )
        Exception.__init__(self, message)
