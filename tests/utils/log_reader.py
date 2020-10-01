# Copyright 2014-2020 Scalyr Inc.
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

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
from six.moves import range

if False:  # NOSONAR
    from typing import Optional

import re
import threading
import time
from io import open
import collections

import six

ErrorPatternInfo = collections.namedtuple("ErrorPatternInfo", ["pattern", "message"])


class LogReaderError(Exception):
    pass


class LogReaderTimeoutError(LogReaderError):
    pass


class LogReader(threading.Thread):
    """Reader that allows to read file and wait for new lines"""

    def __init__(self, file_path):
        super(LogReader, self).__init__()
        self._file_path = file_path
        self._file = open(six.text_type(file_path), "r")
        self._error_line_patterns = dict()
        self._lines = list()

    def _check_line_for_error(self, line):
        for pattern, (compiled_pattern, message) in self._error_line_patterns.items():
            if compiled_pattern.match(line):
                if not message:
                    message = "Log file {0} contains error line: '{1}'. Pattern: {2}.".format(
                        self._file_path, line, pattern
                    )
                raise LogReaderError(message)

    def _handle_new_line(self, line):
        self._lines.append(line)
        self._check_line_for_error(line)

    def _read_line(self):
        line = self._file.readline()
        if line:
            self._handle_new_line(line)

        return line

    def wait_for_next_line(self, timeout=10):
        timeout_time = time.time() + timeout
        while True:
            line = self._read_line()
            if line:
                return line

            if time.time() >= timeout_time:
                raise LogReaderTimeoutError(
                    "Timeout of %s seconds reached while waiting for metrics" % timeout
                )

            time.sleep(0.01)

    def go_to_end(self):
        while True:
            line = self._read_line()
            if not line:
                break

        pass

    def wait_for_lines(self, line_number):
        for _ in range(line_number):
            self.wait_for_next_line()

    @property
    def last_line(self):
        if len(self._lines):
            return self._lines[-1]

    def wait_for_matching_line(self, pattern, timeout=10):
        compiled_pattern = re.compile(pattern)
        while True:
            line = self.wait_for_next_line(timeout=timeout)
            if compiled_pattern.match(line):
                return line

    def wait(self, seconds):
        """
        Keep checking for new lines for some period of time in 'seconds'.
        """
        stop_time = time.time() + seconds
        while True:
            try:
                self.wait_for_next_line()
            except LogReaderTimeoutError:
                continue

            if time.time() >= stop_time:
                break

    def add_error_check(self, pattern, message=None):
        compiled_pattern = re.compile(pattern)
        info = ErrorPatternInfo(compiled_pattern, message)
        self._error_line_patterns[pattern] = info


class AgentLogReader(LogReader):
    def __init__(self, file_path):
        super(AgentLogReader, self).__init__(file_path)
        self.add_error_check(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z ERROR")


class LogMetricReader(LogReader):
    """Subclass that allows to read and wait for particular metric."""

    LINE_PATTERN = None  # type: Optional[six.text_type]

    def __init__(self, file_path):
        super(LogMetricReader, self).__init__(file_path)
        self.current_metrics = dict()

    def _parse_line(self, line):
        m = re.match(type(self).LINE_PATTERN, line)
        metric_name = m.group("metric_name")
        metric_value_string = m.group("metric_value")

        if metric_value_string.isdigit():
            metric_value = int(metric_value_string)
        else:
            try:
                metric_value = float(metric_value_string)
            except ValueError:
                metric_value = metric_value_string

        return metric_name, metric_value

    def _handle_new_line(self, line):
        super(LogMetricReader, self)._handle_new_line(line)
        name, value = self._parse_line(line)
        self.current_metrics[name] = value

    def wait_for_metrics_exist(self, names, timeout=10):
        timeout_time = time.time() + timeout
        while True:
            needed_metrics = dict()
            for name in names:
                value = self.current_metrics.get(name)
                if value is None:
                    break
                needed_metrics[name] = value
            else:
                return needed_metrics

            try:
                self.wait_for_next_line()
            except LogReaderTimeoutError():
                if time.time() >= timeout_time:
                    raise LogReaderTimeoutError(
                        "Timeout of %s seconds reached while waiting for metrics"
                        % (timeout)
                    )

            time.sleep(0.01)

    def wait_for_metrics_change(
        self, metric_names, previous_values, predicate, timeout=10
    ):
        timeout_time = time.time() + timeout
        while True:
            try:
                self.wait_for_next_line()
            except LogReaderTimeoutError:
                if time.time() >= timeout_time:
                    raise
                else:
                    continue

            current_values = {name: self.current_metrics[name] for name in metric_names}

            predicate_results = [
                predicate(current_values[name], previous_values[name])
                for name in metric_names
            ]

            if all(predicate_results):
                return current_values
            time.sleep(0.1)

    def wait_for_metrics_increase(self, metric_names, previous_values, timeout=10):
        self.wait_for_metrics_change(
            metric_names, previous_values, lambda cur, prev: cur > prev, timeout=timeout
        )

    def wait_for_metrics_increment(self, metric_names, previous_values, timeout=10):
        self.wait_for_metrics_change(
            metric_names,
            previous_values,
            lambda cur, prev: prev + 1 == cur,
            timeout=timeout,
        )
