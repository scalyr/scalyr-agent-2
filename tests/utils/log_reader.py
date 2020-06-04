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

import re
import threading
import time
from io import open
import collections

import six


class LogReader(threading.Thread):
    """Reader that allows to read file in separate thread and read and wait for new lines"""

    def __init__(self, file_path):
        super(LogReader, self).__init__()
        self.daemon = True
        self._file = open(six.text_type(file_path), "r")
        self._stop_event = threading.Event()
        self._lines_lock = threading.Lock()
        self._start_cv = threading.Condition()
        self._has_data = False
        self._lines = collections.deque(maxlen=1000)
        self._wait_for_line_cv = threading.Condition()

        self._has_new_line = False

    def handle_new_line(self, line):
        with self._lines_lock:
            self._lines.append(line)
        with self._wait_for_line_cv:
            self._has_new_line = True
            self._wait_for_line_cv.notify()

    def run(self):
        def get_line():
            while not self._stop_event.is_set():
                _line = self._file.readline()
                if _line:
                    return _line
                time.sleep(0.1)

        get_line()
        with self._start_cv:
            self._has_data = True
            self._start_cv.notify()
        self._file.seek(0)
        while not self._stop_event.is_set():
            line = get_line()
            self.handle_new_line(line)

    def start(self, wait_for_data=False):
        super(LogReader, self).start()
        if not wait_for_data:
            return
        with self._start_cv:
            while not self._has_data:
                self._start_cv.wait(0.1)
        return

    @property
    def lines(self):
        with self._lines_lock:
            return list(self._lines)

    def wait_for_new_line(self, timeout=10):
        start_time = time.time()
        timeout_time = start_time + timeout

        with self._wait_for_line_cv:
            while not self._has_new_line:
                if time.time() >= timeout_time:
                    raise ValueError(
                        "timeout of %s seconds reached while waiting for metrics"
                        % (timeout)
                    )

                self._wait_for_line_cv.wait(0.1)
            self._has_new_line = False
            with self._lines_lock:
                return self._lines[-1]


class LogMetricReader(LogReader):
    """Subclass that allows to read and wait for particular metric."""

    LINE_PATTERN = None  # type: Optional[six.text_type]

    def __init__(self, file_path):
        super(LogMetricReader, self).__init__(file_path)
        self._current_metrics = dict()

    def handle_new_line(self, line):
        super(LogMetricReader, self).handle_new_line(line)
        name, value = self._parse_line(line)
        with self._lines_lock:
            self._current_metrics[name] = value

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

    def get_metrics(self, names, timeout=10):
        def get():
            _metrics = dict()
            for name in names:
                metric_value = self._current_metrics.get(name)
                if metric_value is None:
                    return None
                _metrics[name] = metric_value
            return _metrics

        start_time = time.time()
        timeout_time = start_time + timeout

        while not self._stop_event.is_set():
            with self._lines_lock:
                metrics = get()
            if metrics is not None:
                return metrics

            if time.time() >= timeout_time:
                raise ValueError(
                    "timeout of %s seconds reached while waiting for metrics"
                    % (timeout)
                )

            time.sleep(0.1)

    def get_metric(self, name):
        metrics = self.get_metrics([name])
        return metrics[name]

    def wait_for_metrics_change(self, metric_names, previous_values, predicate):
        while not self._stop_event.is_set():
            current_values = self.get_metrics(metric_names)

            predicate_results = [
                predicate(current_values[name], previous_values[name])
                for name in metric_names
            ]

            if all(predicate_results):
                return
            time.sleep(0.1)

    def wait_for_metrics_increase(self, metric_names, previous_values):
        self.wait_for_metrics_change(
            metric_names, previous_values, lambda cur, prev: cur > prev,
        )

    def wait_for_metrics_increment(self, metric_names, previous_values):
        self.wait_for_metrics_change(
            metric_names, previous_values, lambda cur, prev: prev + 1 == cur
        )
