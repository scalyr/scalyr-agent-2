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

if False:  # NOSONAR
    from typing import Optional
    from typing import List
    from typing import Dict
    from typing import Tuple
    from typing import Generator
    from typing import Any

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
    """
    Reader that allows to read file and to wait for new lines,
    wait for new lines with some conditions or patterns and etc.
    """

    def __init__(self, file_path):
        super(LogReader, self).__init__()
        self._file_path = file_path
        self._file = open(six.text_type(file_path), "r")
        self._error_line_patterns = dict()
        self._lines = list()

    def add_error_check(self, pattern, message=None):
        # type: (six.text_type, six.text_type) -> None
        """
        Add new regex pattern to match every incoming line.
        In case of match, those lines are considered as errors and exception is raised.
        :param pattern: Regular expression pattern.
        :param message: Additional message to show when error log line is found.
        """
        compiled_pattern = re.compile(pattern)
        info = ErrorPatternInfo(compiled_pattern, message)
        self._error_line_patterns[pattern] = info

    def _check_line_for_error(self, line):
        # type: (six.text_type) -> None
        """
        Match new line with patters that must be caught as error.
        """
        for pattern, (compiled_pattern, message) in self._error_line_patterns.items():
            if compiled_pattern.match(line):
                if not message:
                    message = (
                        "Log file {0} contains error line: '{1}'. Pattern: {2}.".format(
                            self._file_path, line, pattern
                        )
                    )
                raise LogReaderError(message)

    def _new_line_callback(self, line):
        # type: (six.text_type) -> None
        """
        Callback which is invoked when new line is read.
        """
        self._lines.append(line)
        self._check_line_for_error(line)

    def _line_generator(self):  # type: () -> Generator
        """Generator that reads all available lines."""
        for line in self._file:
            line = line.strip("\n")
            self._new_line_callback(line)
            yield line

    def _line_generator_blocking(self, timeout=10):  # type: (float) -> Generator
        """
        Wraps '_line_generator' and yields new log lines until timeout is reached.
        This can be used to wait for new log lines without reimplementing timeout logic.
        """
        timeout_time = time.time() + timeout
        while True:
            line_generator = self._line_generator()
            try:
                line = next(line_generator)
                yield line
            except StopIteration:
                if time.time() >= timeout_time:
                    raise LogReaderTimeoutError(
                        "Timeout of %s seconds reached while waiting for new line. Accumulated lines:\n%s"
                        % (timeout, "\n".join(self._lines))
                    )
                time.sleep(0.01)

    def wait_for_next_line(self, timeout=10):  # type: (float) -> six.text_type
        """
        Waits for new line from the log file. Also returns this line for more convenience.
        """
        return next(self._line_generator_blocking(timeout=timeout))

    def go_to_end(self):
        """
        Just goes to the end of the file. it is useful when there is no need to wait for some particular line,
        but there is need to check all new lines (for errors specified by 'add_error_check' for example.).
        It does not block or wait, it just reads and processes new lines until EOF.
        """
        # TODO: make LogReader do this autimatically by using ContextManager.

        for _ in self._line_generator():
            pass

    def wait_for_matching_line(self, pattern, timeout=10):  # type: ignore
        # type: (six.text_type, int) -> Optional[six.text_type]
        """
        Wait for line which matches to provided pattern.
        """
        compiled_pattern = re.compile(pattern)

        for line in self._line_generator_blocking(timeout=timeout):
            if compiled_pattern.match(line):
                return line

    def wait(self, seconds):
        # type: (float) -> None
        """
        Keep checking for new lines for some period of time(in seconds)'.
        """
        stop_time = time.time() + seconds

        while True:
            self.go_to_end()
            time.sleep(0.01)
            if time.time() >= stop_time:
                break

    @property
    def last_line(self):  # type: () -> six.text_type
        if self._lines:
            return self._lines[-1]
        else:
            return ""


class AgentLogReader(LogReader):
    """
    Generic reader for agent log.
    """

    def __init__(self, file_path):
        super(AgentLogReader, self).__init__(file_path)
        self.add_error_check(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z ERROR")


class LogMetricReader(LogReader):
    """
    Subclass that allows to read and wait for particular metrics.
    """

    LINE_PATTERN = ""  # type: six.text_type

    def __init__(self, file_path):
        super(LogMetricReader, self).__init__(file_path)
        self.current_metrics = dict()

    def _parse_line(self, line):
        # type: (six.text_type) -> Tuple
        """
        Parse metric log line.
        """
        m = re.match(type(self).LINE_PATTERN, line)
        if not m:
            raise LogReaderError("Line: '{}' can not be parsed.")
        metric_name = m.group("metric_name")
        metric_value_string = m.group("metric_value")

        if metric_value_string.isdigit():
            metric_value = int(metric_value_string)  # type: Any[int, float]
        else:
            try:
                metric_value = float(metric_value_string)
            except ValueError:
                metric_value = metric_value_string

        return metric_name, metric_value

    def _new_line_callback(self, line):  # type: (six.text_type) -> None
        """
        Override this callback to parse metrics from new line.
        :return:
        """
        super(LogMetricReader, self)._new_line_callback(line)
        name, value = self._parse_line(line)
        self.current_metrics[name] = value

    def wait_for_metrics_exist(self, names, timeout=10):  # type: ignore
        # type: (List[six.text_type], int) -> Dict[six.text_type, six.text_type]
        """
        Waits until all needed metrics are presented in log file at least once.
        :param names: list on needed metric names.
        :return: metric_name -> metric_value dict with needed metrics.
        """
        remaining_metrics = set(names)
        for _ in self._line_generator_blocking(timeout=timeout):
            for name in list(remaining_metrics):
                value = self.current_metrics.get(name)
                if value is not None:
                    remaining_metrics.remove(name)
            if len(remaining_metrics) == 0:
                return {name: self.current_metrics[name] for name in names}

    def wait_for_metrics_equal(
        self, expected, timeout=10
    ):  # type: (Dict, float) -> Dict
        """
        Wait until current metric values equals to values which are specified in the 'expected' dict.
        :param expected: metric_name -> value pairs with expected values if specified metrics.
        :return: metric_name -> metric_value dict with needed metrics.
        """

        line_gen = self._line_generator_blocking(timeout=timeout)
        while True:
            needed_metrics = {
                name: self.current_metrics[name] for name in expected.keys()
            }
            if needed_metrics == expected:
                return needed_metrics

            # read for other line only after current metrics are evaluated.
            next(line_gen)
