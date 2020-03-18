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
import tempfile

import mock

import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase


class ScalyrLoggingTest(BaseScalyrLogCaptureTestCase):
    def setUp(self):
        super(ScalyrLoggingTest, self).setUp()
        self.__log_path = self.agent_log_path
        self.__logger = scalyr_logging.getLogger("scalyr_agent.agent_main")
        self.__logger.set_keep_last_record(False)

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
        metric_file_path = tempfile.mktemp(".log")

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

    def test_metric_logging_metric_name_blacklist(self):
        monitor_instance = ScalyrLoggingTest.FakeMonitor("testing")
        monitor_instance._metric_name_blacklist = ["name1", "name3"]
        metric_file_path = tempfile.mktemp(".log")

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

        monitor_1_config = {"module": "foo1", "metric_name_blacklist": ["a", "b"]}
        monitor_1_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo1(1)"
        )
        monitor_1 = ScalyrMonitor(
            monitor_config=monitor_1_config, logger=monitor_1_logger
        )
        monitor_1_metric_file_path = tempfile.mktemp(".log")

        monitor_2_config = {"module": "foo2", "metric_name_blacklist": ["c", "d"]}
        monitor_2_logger = scalyr_logging.getLogger(
            "scalyr_agent.builtin_monitors.foo2(1)"
        )
        monitor_2 = ScalyrMonitor(
            monitor_config=monitor_2_config, logger=monitor_1_logger
        )
        monitor_2_metric_file_path = tempfile.mktemp(".log")

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
        metric_file_path = tempfile.mktemp(".log")

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
        metric_file_path = tempfile.mktemp(".log")

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
        metric_file_path = tempfile.mktemp(".log")

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

        metric_file_one = tempfile.mktemp(".log")
        metric_file_two = tempfile.mktemp(".log")

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
        metric_file_path = tempfile.mktemp(".log")

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
        # NOTE: Actual value which is being used for the rate limitting is the formatted value
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

    class FakeMonitor(object):
        """Just a simple class that we use in place of actual Monitor objects when reporting metrics."""

        def __init__(self, name):
            self.__name = name
            self.reported_lines = 0
            self.errors = 0
            self._logger = mock.Mock()
            self._metric_name_blacklist = []

        def increment_counter(self, reported_lines=0, errors=0):
            """Increment some of the counters pertaining to the performance of this monitor.
            """
            self.reported_lines += reported_lines
            self.errors += errors
