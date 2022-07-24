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
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

import sys
import types

__author__ = "czerwin@scalyr.com"

import os
import logging
import tempfile
import hashlib

import mock

import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.scalyr_monitor import ScalyrMonitor
from scalyr_agent.metrics.base import clear_internal_cache
from scalyr_agent.metrics.functions import RateMetricFunction
from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase
from scalyr_agent.test_base import skipIf


class ScalyrLoggingTest(BaseScalyrLogCaptureTestCase):
    def setUp(self):
        super(ScalyrLoggingTest, self).setUp()
        self.__log_path = self.agent_log_path
        self.__logger = scalyr_logging.getLogger("scalyr_agent.agent_main")
        self.__logger.set_keep_last_record(False)

        clear_internal_cache()

    def tearDown(self):
        super(ScalyrLoggingTest, self).tearDown()
        clear_internal_cache()

    def test_output_to_file(self):
        self.__logger.info("Hello world")
        self.assertLogFileContainsLineRegex(expression="Hello world")

    def test_component_name(self):
        self.assertEquals(self.__logger.component, "core")
        self.assertEquals(scalyr_logging.getLogger("scalyr_agent").component, "core")
        self.assertEquals(
            scalyr_logging.getLogger("scalyr_agent.foo").component, "core"
        )
        self.assertEquals(
            scalyr_logging.getLogger("scalyr_agent.foo.bar").component, "core"
        )
        self.assertEquals(
            scalyr_logging.getLogger("scalyr_agent.builtin_monitors.foo").component,
            "monitor:foo",
        )
        self.assertEquals(
            scalyr_logging.getLogger("scalyr_agent.builtin_monitors.foo(ok)").component,
            "monitor:foo(ok)",
        )

    def test_formatter(self):
        # The format should be something like:
        # 2014-05-11 16:55:06.236 INFO [core] [scalyr_logging_test.py:28] Test line 5
        self.__logger.info("Test line %d", 5)
        expression = (
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.\d{3}Z INFO \[core\] "
            r"\[.*\.py:\d+\] Test line 5"
        )
        self.assertLogFileContainsLineRegex(expression=expression)

    def test_debug_level_for_subset_of_loggers(self):
        logger1 = scalyr_logging.getLogger("logger1")
        logger2 = scalyr_logging.getLogger("logger2")
        logger3 = scalyr_logging.getLogger("logger3")

        logger1.info("XX Test info 1")
        logger1.debug("XX Test debug 1")

        logger2.info("XX Test info 2")
        logger2.debug("XX Test debug 2")

        logger3.info("XX Test info 3")
        logger3.debug("XX Test debug 3")

        # 1. Default behavior - only INFO is enabled
        self.assertLogFileContainsLineRegex(expression="XX Test info 1")
        self.assertLogFileContainsLineRegex(expression="XX Test info 2")
        self.assertLogFileContainsLineRegex(expression="XX Test info 3")

        self.assertLogFileDoesntContainsLineRegex(
            expression="XX Test debug 1", file_path=self.agent_debug_log_path
        )
        self.assertLogFileDoesntContainsLineRegex(
            expression="XX Test debug 2", file_path=self.agent_debug_log_path
        )
        self.assertLogFileDoesntContainsLineRegex(
            expression="XX Test debug 3", file_path=self.agent_debug_log_path
        )

        # 2. Now we enable debug level for 2 loggers only
        scalyr_logging.set_log_level(
            level=logging.INFO, debug_level_logger_names=["logger2", "logger3"]
        )

        logger1.info("YY Test info 1")
        logger1.debug("YY Test debug 1")

        logger2.info("YY Test info 2")
        logger2.debug("YY Test debug 2")

        logger3.info("YY Test info 3")
        logger3.debug("YY Test debug 3")

        self.assertLogFileContainsLineRegex(expression="YY Test info 1")
        self.assertLogFileContainsLineRegex(expression="YY Test info 2")
        self.assertLogFileContainsLineRegex(expression="YY Test info 3")

        self.assertLogFileDoesntContainsRegex(
            expression="YY Test debug 1", file_path=self.agent_debug_log_path
        )
        self.assertLogFileContainsLineRegex(
            expression="YY Test debug 2", file_path=self.agent_debug_log_path
        )
        self.assertLogFileContainsLineRegex(
            expression="YY Test debug 3", file_path=self.agent_debug_log_path
        )

    def test_error_code(self):
        self.__logger.warn("Bad result", error_code="statusCode")
        expression = r'\[error="statusCode"\] Bad result'
        self.assertLogFileContainsLineRegex(expression=expression)

    def test_child_modules(self):
        child = scalyr_logging.getLogger("scalyr_agent.foo.bar")
        child.info("Child statement")
        expression = "Child statement"
        self.assertLogFileContainsLineRegex(expression=expression)

    def test_sibling_modules(self):
        child = scalyr_logging.getLogger("external_package.my_monitor")
        child.info("Sibling statement")
        expression = "Sibling statement"
        self.assertLogFileContainsLineRegex(expression=expression)

    def test_metric_logging(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.emit_value("test_name", 5, {"foo": 5})

        self.assertEquals(monitor_instance.reported_lines, 1)

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="test_name 5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="foo=5"
        )
        self.assertLogFileDoesntContainsLineRegex(expression="foo=5")

        monitor_logger.closeMetricLog()

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_metric_logging_custom_timestamp(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        timestamp_ms1 = 1650021068015
        timestamp_ms2 = 1650021068016

        expected_line_prefix = r"2022-04-15 11:11:08.015Z \[foo\(1\)\] test_name "

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.emit_value("test_name", 1, {"foo": 5}, timestamp=timestamp_ms1)
        monitor_logger.emit_value("test_name", 2, {"foo": 5}, timestamp=timestamp_ms1)
        monitor_logger.emit_value("test_name", 3, {"foo": 5}, timestamp=timestamp_ms1)
        monitor_logger.emit_value("test_name", 4, {"foo": 5}, timestamp=timestamp_ms1)
        monitor_logger.emit_value(
            "test_name",
            5,
            {"foo": 5, "timestamp": timestamp_ms2},
            timestamp=timestamp_ms1,
        )

        self.assertEquals(monitor_instance.reported_lines, 5)

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression=expected_line_prefix + "1 foo=5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression=expected_line_prefix + "2 foo=5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression=expected_line_prefix + "3 foo=5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression=expected_line_prefix + "4 foo=5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression=expected_line_prefix + "5 foo=5 timestamp=1650021068016",
        )
        monitor_logger.closeMetricLog()

    def test_metric_logging_reserved_extra_field_names_are_sanitized(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        extra_fields = {
            # Reserved field names
            "logfile": "logfile",
            "monitor": "monitor",
            "metric": "metric",
            "value": "value",
            "instance": "instance",
            "severity": "severity",
            # Non reserved field names
            "foo": "bar",
            "bar": "baz",
        }

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.emit_value("test_name", 5, extra_fields)

        self.assertEquals(monitor_instance.reported_lines, 1)

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="test_name 5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name 5 bar="baz" foo="bar" instance_="instance" logfile_="logfile" metric_="metric" monitor_="monitor" severity_="severity" value_="value"',
        )

        monitor_logger.closeMetricLog()

    def test_metric_logging_extra_fields_are_sorted(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.emit_value("test_name", 5, {"g": 9, "c": 5, "a": 7, "b": 8})

        self.assertEquals(monitor_instance.reported_lines, 1)

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="test_name 5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="a=7 b=8 c=5 g=9"
        )
        self.assertLogFileDoesntContainsLineRegex(expression="a=7")
        self.assertLogFileDoesntContainsLineRegex(expression="g=9")

        monitor_logger.closeMetricLog()

    def test_metric_logging_metric_name_blacklist(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._metric_name_blacklist = ["name1", "name3"]

        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.emit_value("name1", 5, {"foo": 5})
        monitor_logger.emit_value("name2", 6, {"foo": 6})
        monitor_logger.emit_value("name3", 7, {"foo": 7})
        monitor_logger.emit_value("name4", 8, {"foo": 8})

        self.assertEquals(monitor_instance.reported_lines, 2)

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="name2"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="foo=6"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="name4"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="foo=8"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="name1"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="name3"
        )

        monitor_logger.closeMetricLog()

    def test_metric_logging_metric_name_blacklist_actual_monitor_class(self):
        from scalyr_agent.scalyr_monitor import ScalyrMonitor

        global_config = mock.Mock()
        global_config.metric_functions_cleanup_interval = 0
        global_config.instrumentation_stats_log_interval = 300
        global_config.calculate_rate_metric_names = []

        monitor_1_config = {"module": "foo1", "metric_name_blacklist": ["a", "b"]}
        monitor_1_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo1(1)"
        )
        monitor_1 = ScalyrMonitor(
            monitor_config=monitor_1_config,
            logger=monitor_1_logger,
            global_config=global_config,
        )

        metric_file_fd, monitor_1_metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_2_config = {"module": "foo2", "metric_name_blacklist": ["c", "d"]}
        monitor_2_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo2(1)"
        )
        monitor_2 = ScalyrMonitor(
            monitor_config=monitor_2_config,
            logger=monitor_1_logger,
            global_config=global_config,
        )

        metric_file_fd, monitor_2_metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_1_logger.openMetricLogForMonitor(monitor_1_metric_file_path, monitor_1)

        monitor_1_logger.emit_value("a", 1)
        monitor_1_logger.emit_value("b", 2)
        monitor_1_logger.emit_value("c", 3)
        monitor_1_logger.emit_value("d", 4)

        self.assertLogFileContainsLineRegex(
            file_path=monitor_1_metric_file_path, expression="d"
        )
        self.assertLogFileContainsLineRegex(
            file_path=monitor_1_metric_file_path, expression="d"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=monitor_1_metric_file_path, expression="a"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=monitor_1_metric_file_path, expression="b"
        )

        monitor_1_logger.closeMetricLog()

        monitor_2_logger.openMetricLogForMonitor(monitor_2_metric_file_path, monitor_2)

        monitor_2_logger.emit_value("a", 1)
        monitor_2_logger.emit_value("b", 2)
        monitor_2_logger.emit_value("c", 3)
        monitor_2_logger.emit_value("d", 4)

        self.assertLogFileContainsLineRegex(
            file_path=monitor_2_metric_file_path, expression="a"
        )
        self.assertLogFileContainsLineRegex(
            file_path=monitor_2_metric_file_path, expression="a"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=monitor_2_metric_file_path, expression="c"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=monitor_2_metric_file_path, expression="d"
        )

        monitor_2_logger.closeMetricLog()

    def test_logging_to_metric_log(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")

        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.info("foobaz is fine", emit_to_metric_log=True)

        self.assertEquals(monitor_instance.reported_lines, 1)

        # The value should only appear in the metric log file and not the main one.
        expression = "foobaz is fine"
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression=expression
        )
        self.assertLogFileDoesntContainsLineRegex(expression=expression)

        monitor_logger.closeMetricLog()

    def test_metric_logging_with_bad_name(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")

        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        monitor_logger.emit_value("1name", 5)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="sa_1name"
        )

        monitor_logger.emit_value("name+hi", 5)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="name_hi"
        )

        monitor_logger.emit_value("name", 5, {"hi+": 6})
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="hi_"
        )

        monitor_logger.closeMetricLog()

    def test_errors_for_monitor(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")

        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        monitor_logger.error("Foo")

        self.assertEquals(monitor_instance.errors, 1)

        monitor_logger.closeMetricLog()

    def test_module_with_different_metric_logs(self):
        monitor_one = ScalyrLoggingTest.FakeMonitor("testing one")
        monitor_two = ScalyrLoggingTest.FakeMonitor("testing two")

        metric_file_one_fd, metric_file_one = tempfile.mkstemp(".log")
        metric_file_two_fd, metric_file_two = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_one_fd)
        os.close(metric_file_two_fd)

        logger_one = scalyr_logging.getLogger("scalyr_agent.builtin_monitors.foo(1)")
        logger_two = scalyr_logging.getLogger("scalyr_agent.builtin_monitors.foo(2)")

        logger_one.openMetricLogForMonitor(metric_file_one, monitor_one)
        logger_two.openMetricLogForMonitor(metric_file_two, monitor_two)

        logger_one.report_values({"foo": 5})
        logger_two.report_values({"bar": 4})

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_one, expression="foo=5"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_two, expression="foo=5"
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_two, expression="bar=4"
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_one, expression="bar=4"
        )

        logger_one.closeMetricLog()
        logger_two.closeMetricLog()

    def test_pass_in_module_with_metric(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")

        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)
        scalyr_logging.getLogger("scalyr_agent.builtin_monitors.foo").report_values(
            {"foo": 5}, monitor=monitor_instance
        )

        # The value should only appear in the metric log file and not the main one.
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression="foo=5"
        )
        self.assertLogFileDoesntContainsLineRegex(expression="foo=5")

        monitor_logger.closeMetricLog()

    def test_rate_limit_throttle_write_rate(self):
        """
        Drop log messages with log size > max_write_burst and other following
        log messages if log write rate is low.
        """
        scalyr_logging.set_log_destination(
            use_disk=True,
            logs_directory=os.path.dirname(self.__log_path),
            agent_log_file_path=self.__log_path,
            max_write_burst=250,
            log_write_rate=0,
        )
        self.__logger = scalyr_logging.getLogger("scalyr_agent.agent_main")

        string_300 = "a" * 300

        self.__logger.info("First message")
        self.assertLogFileContainsLineRegex(expression="First message")

        self.__logger.info("Dropped message %s", string_300)
        self.assertLogFileDoesntContainsLineRegex(expression="Dropped message")

        self.__logger.info("Second message")
        self.assertLogFileDoesntContainsLineRegex(expression="Second message")

    def test_rate_limit_no_write_rate(self):
        """
        Drop log messages with log size > max_write_burst but do not drop
        following small log messages
        """
        max_write_burst = 500
        log_write_rate = 20000

        scalyr_logging.set_log_destination(
            use_disk=True,
            logs_directory=os.path.dirname(self.__log_path),
            agent_log_file_path=self.__log_path,
            max_write_burst=max_write_burst,
            log_write_rate=log_write_rate,
        )
        self.__logger = scalyr_logging.getLogger("scalyr_agent.agent_main")

        self.__logger.set_keep_last_record(True)
        # NOTE: Actual value which is being used for the rate limiting is the formatted value
        # and that value contains much more information than the string we generate here.
        # This means that 450 + common formatted string data will aways be > 500 and we need to
        # make sure that "max_write_burst" value we use is large enough so formatted "First
        # message" and "Second message" (with a warning) fit in that value, otherwise depending
        # on the timing and fill rate, the test may fail.
        string_450 = "a" * 450

        self.__logger.info("First message")
        self.assertLogFileContainsLineRegex(expression="First message")

        first_message_record = self.__logger.last_record
        self.assertEqual(first_message_record.message, "First message")

        self.__logger.info("Dropped message %s", string_450)
        self.assertLogFileDoesntContainsLineRegex(expression="Dropped message")

        self.__logger.info("Second message")

        second_message_record = self.__logger.last_record
        self.assertEqual(second_message_record.message, "Second message")

        # Verify that formatted first mesage + second message length is not larger then 500
        # (max_write_burst) which would indicate invalid test which may intermediatly fail
        # depending on the test timing
        self.assertEqual(1, second_message_record.rate_limited_dropped_records)

        if (
            first_message_record.formatted_size + second_message_record.formatted_size
        ) >= max_write_burst:
            self.fail(
                "Length of the formatted first and second mesage string is longer than "
                "%s bytes (max_write_burst). Increase max_write_burst used or update the "
                "strings otherwise tests may occasionally fail." % (max_write_burst)
            )

        self.assertLogFileContainsLineRegex(expression="Second message")
        expression = "Warning, skipped writing 1 log lines"
        self.assertLogFileContainsLineRegex(expression=expression)
        self.assertTrue(second_message_record.rate_limited_result)
        self.assertTrue(second_message_record.rate_limited_set)

    def test_limit_once_per_x_secs(self):
        log = scalyr_logging.getLogger("scalyr_agent.foo")
        log.info(
            "First record",
            limit_once_per_x_secs=60.0,
            limit_key="foo",
            current_time=0.0,
        )
        log.info(
            "Second record",
            limit_once_per_x_secs=60.0,
            limit_key="foo",
            current_time=1.0,
        )
        log.info(
            "Third record",
            limit_once_per_x_secs=60.0,
            limit_key="foo",
            current_time=61.0,
        )

        self.assertLogFileContainsLineRegex(expression="First record")
        self.assertLogFileDoesntContainsLineRegex(expression="Second record")
        self.assertLogFileContainsLineRegex(expression="Third record")

        # Now test with different keys.
        log.info(
            "First record",
            limit_once_per_x_secs=30.0,
            limit_key="foo",
            current_time=0.0,
        )
        log.info(
            "Second record",
            limit_once_per_x_secs=60.0,
            limit_key="bar",
            current_time=1.0,
        )
        log.info(
            "Third record",
            limit_once_per_x_secs=30.0,
            limit_key="foo",
            current_time=31.0,
        )
        log.info(
            "Fourth record",
            limit_once_per_x_secs=60.0,
            limit_key="bar",
            current_time=31.0,
        )

        self.assertLogFileContainsLineRegex(expression="First record")
        self.assertLogFileContainsLineRegex(expression="Second record")
        self.assertLogFileContainsLineRegex(expression="Third record")
        self.assertLogFileDoesntContainsLineRegex(expression="Fourth record")

    def test_force_valid_metric_or_field_name(self):
        name = "abc$#%^&123"
        fixed_name = scalyr_logging.AgentLogger.force_valid_metric_or_field_name(name)
        self.assertEqual(fixed_name, "abc_____123")

        name2 = "abc123"
        fixed_name2 = scalyr_logging.AgentLogger.force_valid_metric_or_field_name(name2)
        self.assertEqual(fixed_name2, name2)

    def fake_std_write(self, a, b):
        self.ran_std_output = True

    def test_output_to_file_with_stdout(self):
        self.ran_std_output = False
        stdout_bkp = sys.stdout.write
        sys.stdout.write = types.MethodType(self.fake_std_write, sys.stdout)
        try:
            self.__logger.info("Hello world", force_stdout=True)
            self.assertLogFileContainsLineRegex(expression="Hello world")
            self.assertTrue(self.ran_std_output)
        finally:
            sys.stdout.write = stdout_bkp
            self.ran_std_output = False

    def test_output_to_file_with_stderr(self):
        self.ran_std_output = False
        stderr_bkp = sys.stderr.write
        sys.stderr.write = types.MethodType(self.fake_std_write, sys.stderr)
        try:
            self.__logger.info("Hello world", force_stderr=True)
            self.assertLogFileContainsLineRegex(expression="Hello world")
            self.assertTrue(self.ran_std_output)
        finally:
            sys.stderr.write = stderr_bkp
            self.ran_std_output = False

    def test_output_to_file_with_stdout_stderr(self):
        self.ran_std_output = False
        stdout_bkp = sys.stdout.write
        sys.stdout.write = types.MethodType(self.fake_std_write, sys.stdout)
        stderr_bkp = sys.stderr.write
        sys.stderr.write = types.MethodType(self.fake_std_write, sys.stderr)
        try:
            self.__logger.info("Hello world", force_stdout=True)
            self.assertLogFileContainsLineRegex(expression="Hello world")
            self.assertTrue(self.ran_std_output)
            self.ran_std_output = False
            self.__logger.info("Hello world again", force_stderr=True)
            self.assertLogFileContainsLineRegex(expression="Hello world again")
            self.assertTrue(self.ran_std_output)
        finally:
            sys.stdout.write = stdout_bkp
            sys.stderr.write = stderr_bkp
            self.ran_std_output = False

    def test_output_to_file_without_stdout_stderr(self):
        self.ran_std_output = False
        stdout_bkp = sys.stdout.write
        sys.stdout.write = types.MethodType(self.fake_std_write, sys.stdout)
        stderr_bkp = sys.stderr.write
        sys.stderr.write = types.MethodType(self.fake_std_write, sys.stderr)
        try:
            self.__logger.info("Hello world")
            self.assertLogFileContainsLineRegex(expression="Hello world")
            self.assertFalse(self.ran_std_output)
        finally:
            sys.stdout.write = stdout_bkp
            sys.stderr.write = stderr_bkp
            self.ran_std_output = False

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_warn_on_too_many_metrics_cached(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = []
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")
        RateMetricFunction.MAX_RATE_METRICS_COUNT_WARN = 500

        for index in range(0, RateMetricFunction.MAX_RATE_METRICS_COUNT_WARN + 1):
            monitor_instance._global_config.calculate_rate_metric_names.append(
                "fake_monitor_module:test_name_%s" % (index)
            )

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        extra_fields = {"foo1": "bar1"}
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        ts = 1

        for index in range(0, RateMetricFunction.MAX_RATE_METRICS_COUNT_WARN + 1):
            monitor_logger.emit_value(
                "test_name_%s" % (index),
                20,
                extra_fields,
                timestamp=(ts * index) * 1000,
            )

        for index in range(0, RateMetricFunction.MAX_RATE_METRICS_COUNT_WARN + 1):
            monitor_logger.emit_value(
                "test_name_%s" % (index),
                30,
                extra_fields,
                timestamp=(ts * index + 2) * 1000,
            )

        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="test_name_1_rate1"
        )

        # NOTE: Actual reported metrics should be * 3 since we emit two metrics and for each metric
        # expect the first one, rate is calculated and emited
        self.assertEquals(
            monitor_instance.reported_lines,
            (RateMetricFunction.MAX_RATE_METRICS_COUNT_WARN * 3) + 2,
        )
        monitor_instance._logger.warn.assert_called_with(
            "Tracking client side rate for over 20000 metrics. Tracking and calculating rate for that many metrics\ncould add overhead in terms of CPU and memory usage.",
            limit_key="rate-max-count-reached",
            limit_once_per_x_secs=86400,
        )

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_metric_metric_value_not_a_number(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        extra_fields = {"foo1": "bar1"}
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        monitor_logger.emit_value(
            "test_name_2", "nan1", extra_fields, timestamp=10 * 1000
        )
        monitor_logger.emit_value(
            "test_name_2", "nan2", extra_fields, timestamp=20 * 1000
        )
        monitor_logger.emit_value(
            "test_name_2", "nan3", extra_fields, timestamp=30 * 1000
        )

        self.assertEquals(monitor_instance.reported_lines, 3)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 "nan1" foo1="bar1"'
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 "nan2" foo1="bar1"'
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 "nan3" foo1="bar1"'
        )
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="test_name_2_rate"
        )

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_metric_invalid_timestamp(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        extra_fields = {"foo1": "bar1"}
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        monitor_logger.emit_value("test_name_2", 100, extra_fields, timestamp=10 * 1000)

        # Current timestamp = previous_timestamp, should not report a value
        monitor_logger.emit_value("test_name_2", 110, extra_fields, timestamp=10 * 1000)

        # Current timestamp < previous_timestamp, should not report a value
        monitor_logger.emit_value("test_name_2", 120, extra_fields, timestamp=9 * 1000)

        # Time delta between previous and currect collection timestamp is too large, rate should not
        # be calculated
        monitor_logger.emit_value(
            "test_name_2",
            130,
            extra_fields,
            timestamp=(RateMetricFunction.MAX_RATE_TIMESTAMP_DELTA_SECONDS + 60) * 1000,
        )

        self.assertEquals(monitor_instance.reported_lines, 4)

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_new_metric_smaller_than_previous(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        extra_fields = {"foo1": "bar1"}
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        monitor_logger.emit_value("test_name_2", 100, extra_fields, timestamp=10 * 1000)

        # Current metric value is < previous metric value (100)
        monitor_logger.emit_value("test_name_2", 99, extra_fields, timestamp=20 * 1000)

        self.assertEquals(monitor_instance.reported_lines, 2)
        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="test_name_1_rate"
        )

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_metric_not_whitelisted(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        extra_fields = {"foo1": "bar1"}
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        # Metric for which we don't calculate rate
        monitor_logger.emit_value("test_name_1", 20, extra_fields)
        monitor_logger.emit_value("test_name_1", 20, extra_fields)
        monitor_logger.emit_value("test_name_1", 30, extra_fields)

        self.assertEquals(monitor_instance.reported_lines, 3)

        self.assertLogFileDoesntContainsLineRegex(
            file_path=metric_file_path, expression="test_name_1_rate"
        )

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_metric_no_unique_extra_fields_success(
        self,
    ):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        # Metric for which we do calculate rate
        extra_fields = {"foo2": "bar2"}

        ts1 = 10
        ts2 = 70
        ts3 = 130
        ts4 = 190

        monitor_logger.emit_value("test_name_2", 20, extra_fields, timestamp=ts1 * 1000)
        monitor_logger.emit_value("test_name_2", 30, extra_fields, timestamp=ts2 * 1000)
        monitor_logger.emit_value("test_name_2", 40, extra_fields, timestamp=ts3 * 1000)
        monitor_logger.emit_value(
            "test_name_2", 100, extra_fields, timestamp=ts4 * 1000
        )

        # There should be 3 rate metrics emitted (total metrics emitted - 1)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 20 foo2="bar2"'
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 30 foo2="bar2"'
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 40 foo2="bar2"'
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2 100 foo2="bar2"'
        )

        # (30 - 20) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.16667 foo2="bar2"',
        )

        # (40 - 30) / (130 - 70)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.16667 foo2="bar2"',
        )

        # (100 - 40) / (190 - 130)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path, expression='test_name_2_rate 1.0 foo2="bar2"'
        )
        self.assertEquals(monitor_instance.reported_lines, 4 + 3)

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_metric_with_unique_extra_fields_success(
        self,
    ):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2:mode=user",
            "fake_monitor_module:test_name_2:mode=kernel",
        ]
        metric_file_fd, metric_file_path = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd)

        monitor_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(1)"
        )
        monitor_logger.openMetricLogForMonitor(metric_file_path, monitor_instance)

        # Metric for which we do calculate rate
        ts1 = 10
        ts2 = 70
        ts3 = 130
        ts4 = 190

        extra_fields = {"foo2": "bar2", "mode": "user"}

        monitor_logger.emit_value("test_name_2", 10, extra_fields, timestamp=ts1 * 1000)
        monitor_logger.emit_value("test_name_2", 12, extra_fields, timestamp=ts2 * 1000)
        monitor_logger.emit_value("test_name_2", 19, extra_fields, timestamp=ts3 * 1000)
        monitor_logger.emit_value("test_name_2", 33, extra_fields, timestamp=ts4 * 1000)

        extra_fields = {"foo2": "bar2", "mode": "kernel"}

        monitor_logger.emit_value("test_name_2", 20, extra_fields, timestamp=ts1 * 1000)
        monitor_logger.emit_value("test_name_2", 32, extra_fields, timestamp=ts2 * 1000)
        monitor_logger.emit_value("test_name_2", 35, extra_fields, timestamp=ts3 * 1000)
        monitor_logger.emit_value("test_name_2", 40, extra_fields, timestamp=ts4 * 1000)

        # Metric for which we don't calculate rate and should be ignored
        extra_fields = {"foo2": "bar2", "mode": "total"}

        monitor_logger.emit_value("test_name_2", 11, extra_fields, timestamp=ts1 * 1000)
        monitor_logger.emit_value("test_name_2", 12, extra_fields, timestamp=ts2 * 1000)
        monitor_logger.emit_value("test_name_2", 13, extra_fields, timestamp=ts3 * 1000)
        monitor_logger.emit_value("test_name_2", 14, extra_fields, timestamp=ts4 * 1000)

        # There should be 3 rate metrics emitted (total metrics emitted - 1)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 10 foo2="bar2" mode="user"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 12 foo2="bar2" mode="user"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 19 foo2="bar2" mode="user"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 33 foo2="bar2" mode="user"',
        )

        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 20 foo2="bar2" mode="kernel"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 32 foo2="bar2" mode="kernel"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 35 foo2="bar2" mode="kernel"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 40 foo2="bar2" mode="kernel"',
        )

        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 11 foo2="bar2" mode="total"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 12 foo2="bar2" mode="total"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 13 foo2="bar2" mode="total"',
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2 14 foo2="bar2" mode="total"',
        )

        # mode=user
        # (12 - 10) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.03333 foo2="bar2" mode="user"',
        )

        # (19 - 12) / (130 - 70)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.11667 foo2="bar2" mode="user"',
        )

        # (33 - 19) / (190 - 130)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.23333 foo2="bar2" mode="user"',
        )

        # mode=kernel
        # (32 - 20) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.2 foo2="bar2" mode="kernel"',
        )

        # (35 - 32) / (130 - 70)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.05 foo2="bar2" mode="kernel"',
        )

        # (40 - 35) / (190 - 130)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path,
            expression='test_name_2_rate 0.08333 foo2="bar2" mode="kernel"',
        )

        self.assertEquals(monitor_instance.reported_lines, 4 + 4 + 4 + 3 + 3)

    @skipIf(sys.version_info < (2, 8, 0), "Skipping tests under Python <= 2.7")
    def test_emit_value_metric_rate_calculation_no_collision_two_monitors_same_metric_name(
        self,
    ):
        # Ensure there are no collisions in case two monitors use the same metric name
        monitor_instance_1 = ScalyrLoggingTest.FakeMonitor("testing-one")
        monitor_instance_1._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]

        # Same monitor name, but a different instance id
        monitor_instance_2 = ScalyrLoggingTest.FakeMonitor("testing-one", "two")
        monitor_instance_2._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]

        monitor_instance_3 = ScalyrLoggingTest.FakeMonitor("testing-two")
        monitor_instance_3._global_config.calculate_rate_metric_names = [
            "fake_monitor_module:test_name_2"
        ]

        metric_file_fd_1, metric_file_path_1 = tempfile.mkstemp(".log")
        metric_file_fd_2, metric_file_path_2 = tempfile.mkstemp(".log")
        metric_file_fd_3, metric_file_path_3 = tempfile.mkstemp(".log")

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(metric_file_fd_1)
        os.close(metric_file_fd_2)
        os.close(metric_file_fd_3)

        extra_fields = {}

        monitor_logger_1 = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(testing-one)"
        )
        monitor_logger_1.openMetricLogForMonitor(metric_file_path_1, monitor_instance_1)
        monitor_logger_2 = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(testing-one-two)"
        )
        monitor_logger_2.openMetricLogForMonitor(metric_file_path_2, monitor_instance_2)

        monitor_logger_3 = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo(testing-two)"
        )
        monitor_logger_3.openMetricLogForMonitor(metric_file_path_3, monitor_instance_3)

        ts1 = 10
        ts2 = 70

        monitor_logger_1.emit_value(
            "test_name_2", 20, extra_fields, timestamp=ts1 * 1000
        )
        monitor_logger_1.emit_value(
            "test_name_2", 30, extra_fields, timestamp=ts2 * 1000
        )

        self.assertEquals(monitor_instance_1.reported_lines, 2 + 1)

        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_1,
            expression="test_name_2 20",
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_1,
            expression="test_name_2 30",
        )

        # (30 - 20) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_1,
            expression="test_name_2_rate 0.16667",
        )

        monitor_logger_2.emit_value(
            "test_name_2", 80, extra_fields, timestamp=ts1 * 1000
        )
        monitor_logger_2.emit_value(
            "test_name_2", 81, extra_fields, timestamp=ts2 * 1000
        )

        self.assertEquals(monitor_instance_2.reported_lines, 2 + 1)

        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_2,
            expression="test_name_2 80",
        )
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_2,
            expression="test_name_2 81",
        )

        # (81 - 80) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_2,
            expression="test_name_2_rate 0.01667",
        )

        monitor_logger_3.emit_value(
            "test_name_2", 90, extra_fields, timestamp=ts1 * 1000
        )
        monitor_logger_3.emit_value(
            "test_name_2", 95, extra_fields, timestamp=ts2 * 1000
        )

        # (90 - 95) / (70 - 10)
        self.assertLogFileContainsLineRegex(
            file_path=metric_file_path_3,
            expression="test_name_2_rate 0.08333",
        )

    class FakeMonitor(ScalyrMonitor):
        """Just a simple class that we use in place of actual Monitor objects when reporting metrics."""

        def __init__(self, name, monitor_id=None):
            self.__name = name
            self.monitor_id = str(monitor_id or "default")
            self.monitor_module_name = "fake_monitor_module"
            self.short_hash = hashlib.sha256(
                self.__name.encode("utf-8") + b":" + self.monitor_id.encode("utf-8")
            ).hexdigest()[:10]
            self.reported_lines = 0
            self.errors = 0
            self._logger = mock.Mock()
            self._metric_name_blacklist = []

            mock_config = mock.Mock()
            mock_config.calculate_rate_metric_names = []
            mock_config.metric_functions_cleanup_interval = 0
            mock_config.instrumentation_stats_log_interval = 300
            self._global_config = mock_config

        def get_calculate_rate_metric_names(self):
            return []

        def increment_counter(self, reported_lines=0, errors=0):
            """Increment some of the counters pertaining to the performance of this monitor."""
            self.reported_lines += reported_lines
            self.errors += errors
