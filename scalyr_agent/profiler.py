# Copyright 2018 Scalyr Inc.
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
# author:  Imron Alston <imron@scalyr.com>

"""
Module which contains classes and abstractions for CPU and memory profiling.
"""

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

if False:  # NOSONAR
    from typing import Optional
    from typing import Dict
    from typing import List
    from typing import Any

import os
import random
import time
import traceback
from io import open
from abc import ABCMeta
from abc import abstractmethod

import six


try:
    import yappi
except ImportError:
    yappi = None

try:
    import pympler

    from pympler import summary
    from pympler import muppy
    from pympler import tracker
except ImportError:
    pympler = None

try:
    # Only available in stdlib of Python >= 3.4
    import tracemalloc

    # Only available in stdlib of Python >= 3.5
    import linecache
except ImportError:
    tracemalloc = None
    linecache = None

from scalyr_agent.configuration import Configuration
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.util import StoppableThread

__all__ = ["ScalyrProfiler"]

global_log = scalyr_logging.getLogger(__name__)

# Default trace filters for tracemalloc
if tracemalloc:
    # By default we exclude some stdlib code + this module to avoid noise
    DEFAULT_TRACES_FILTERS = [
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, "<unknown>"),
        tracemalloc.Filter(False, tracemalloc.__file__),
        tracemalloc.Filter(False, linecache.__file__),
        tracemalloc.Filter(False, __file__),
        # local dev environment
        tracemalloc.Filter(False, "**/.pyenv/*"),
    ]
else:
    DEFAULT_TRACES_FILTERS = []


class ScalyrProfiler(object):
    """
    Profiler class for CPU and memory profiling.
    """

    def __init__(self, config):
        # type: (Configuration) -> None
        self.__cpu_profiler = CPUProfiler(config=config)
        self.__memory_profiler = MemoryProfiler(config=config)

    def update(self, config, current_time=None):
        # type: (Configuration, Optional[float]) -> None
        """
        Updates the state of the profiler - either enabling or disabling it, based on
        the current time and whether or not the current profiling interval has started/stopped
        """
        self.__cpu_profiler.update(config=config, current_time=current_time)
        self.__memory_profiler.update(config=config, current_time=current_time)


class BaseProfiler(six.with_metaclass(ABCMeta)):
    """
    Base class to be inherited by various profilers.
    """

    def __init__(self, config):
        # type: (Configuration) -> None
        self._profile_start = 0
        self._profile_end = 0

        # Indicates if this profiler is available (aka underlying library is installed)
        self._is_available = False

        # Indicates if this profiler is enabled in the configuration
        self._is_enabled = False

    @abstractmethod
    def is_profiling_enabled(self, config):
        # type: (Configuration) -> bool
        raise NotImplementedError("is_profiling_enabled() not implemented")

    def update(self, config, current_time=None):
        # type: (Configuration, Optional[float]) -> None
        """
        Updates the state of the profiler - either enabling or disabling it, based on the current
        time and whether or not the current profiling interval has started/stopped.
        """
        if not self._is_available:
            return

        current_time = current_time or time.time()

        try:
            # check if profiling is enabled in the config and turn it on/off if necessary
            if self.is_profiling_enabled(config=config):
                if not self._is_enabled:
                    self._update_start_interval(config, current_time)
                    self._is_enabled = True
            else:
                if self._is_running():
                    self._stop(config, current_time)
                self._is_enabled = False

            # only do profiling if we are still enabled
            if not self._is_enabled:
                return

            # check if the current profiling interval needs to start or stop
            if self._is_running():
                if current_time > self._profile_end:
                    self._stop(config, current_time)
                    self._update_start_interval(config, current_time)
            else:
                if current_time >= self._profile_start:
                    self._start(config, current_time)
        except Exception as e:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Failed to update profiler: %s, %s"
                % (six.text_type(e), traceback.format_exc()),
                limit_once_per_x_secs=300,
                limit_key="profiler-update",
            )

    def _start(self, config, current_time):
        # type: (Configuration, float) -> None
        raise NotImplementedError("_start not implemented")

    def _stop(self, config, current_time):
        # type: (Configuration, float) -> None
        raise NotImplementedError("_stop not implemented")

    def _is_running(self):
        # type: () -> bool
        """
        Return true if this profiler is running, False otherwise.
        """
        raise NotImplementedError("_is_running not implemented")

    def _get_random_start_time(self, current_time, maximum_interval_minutes):
        # type: (float, int) -> int
        if maximum_interval_minutes < 1:
            maximum_interval_minutes = 1
        r = random.randint(1, maximum_interval_minutes) * 60
        return int(current_time) + r

    def _update_start_interval(self, config, current_time):
        # type: (Configuration, float) -> None
        self._profile_start = self._get_random_start_time(
            current_time, config.max_profile_interval_minutes
        )
        self._profile_end = self._profile_start + (config.profile_duration_minutes * 60)

        start_in_seconds = self._profile_start - current_time
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "Updating start time to %s (starting profiler in %s seconds)",
            int(self._profile_start),
            int(start_in_seconds),
        )


class CPUProfiler(BaseProfiler):
    """
    CPU profiler based on the yappi package.
    """

    def __init__(self, config):
        super(CPUProfiler, self).__init__(config=config)

        enable_profiling = self.is_profiling_enabled(config=config)

        if enable_profiling:
            if not yappi:
                global_log.warning(
                    "Profiling is enabled, but the `yappi` module couldn't be loaded. "
                    "You need to install `yappi` in order to use profiling.  This can be done "
                    "via pip:  pip install yappi"
                )
                self._is_available = False
            else:
                self._is_available = True

        self._data_file_path = os.path.join(
            config.agent_log_path, config.profile_log_name
        )
        self._allowed_clocks = ["wall", "cpu", "random"]
        self._profile_clock = self._get_clock_type(
            config.profile_clock, self._allowed_clocks, config.profile_clock
        )

        # random is only allowed during initialization, and not via config file changes to
        # ensure the random clock is consistent for the life of the agent.
        # random clocks can still be manually overridden in the agent.json
        self._allowed_clocks = self._allowed_clocks[:2]

    def is_profiling_enabled(self, config):
        return config.enable_profiling or config.enable_cpu_profiling

    def _is_running(self):
        return yappi and yappi.is_running()

    def _get_clock_type(self, clock_type, allowed, default_value):
        """
        gets the clock type.  If clock type is `random` then
        randomly choose from the first 2 elements of the `allowed` array.
        """
        result = default_value
        if clock_type in allowed:
            result = clock_type

        if result == "random":
            r = random.randint(0, 1)
            result = allowed[r]

        return result

    def _start(self, config, current_time):
        yappi.clear_stats()
        clock = self._get_clock_type(
            config.profile_clock, self._allowed_clocks, self._profile_clock
        )
        if clock != self._profile_clock:
            self._profile_clock = clock
            yappi.set_clock_type(self._profile_clock)
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "Starting CPU profiling using '%s' clock. Duration: %d seconds"
            % (self._profile_clock, self._profile_end - self._profile_start),
        )
        yappi.start()

    def _stop(self, config, current_time):
        yappi.stop()
        global_log.log(scalyr_logging.DEBUG_LEVEL_0, "Stopping CPU profiling")
        stats = yappi.get_func_stats()
        if os.path.exists(self._data_file_path):
            os.remove(self._data_file_path)

        # pylint bug https://github.com/PyCQA/pylint/labels/topic-inference
        stats.save(self._data_file_path, "callgrind")  # pylint: disable=no-member

        lines = 0

        # count the lines
        f = open(self._data_file_path)
        try:
            for line in f:
                lines += 1
        finally:
            f.close()

        # write a status message to make it easy to find the end of each profile session
        f = open(self._data_file_path, "a")
        try:
            f.write(
                "\n# %s, %s clock, total lines: %d\n"
                % (self._data_file_path, self._profile_clock, lines)
            )
        finally:
            f.close()

        yappi.clear_stats()
        del stats

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "CPU profiling data written to %s",
            self._data_file_path,
        )


class PymplerPeriodicMemorySummaryCaptureThread(StoppableThread):
    """
    Thread which periodically captures memory summary using pympler package.
    """

    def __init__(
        self,
        capture_interval=10,
        max_items=50,
        frames_count=1,
        include_traceback=False,
        ignore_path_globs=None,
        *args,
        **kwargs
    ):
        # type: (int, int, int, bool, Optional[List[six.text_type]], Any, Any) -> None
        """
        :param capture_interval: How often to capture memory usage snapshot.
        :type capture_interval: ``int``
        """
        super(PymplerPeriodicMemorySummaryCaptureThread, self).__init__(
            name="PymplerPeriodicMemorySummaryCaptureThread"
        )

        # NOTE: frames_count, include_traceback and ignore_path_globs are currently ignored /
        # not supported by pympler profiler
        self._capture_interval = capture_interval
        self._max_items = max_items

        self._profiling_data = []  # type: List[Dict[str, Any]]
        self._tracker = tracker.SummaryTracker()

    def run_and_propagate(self):
        # type: () -> None
        while self._run_state.is_running():
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_5,
                "Performing periodic memory usage capture using pympler",
            )
            self._capture_snapshot()
            self._run_state.sleep_but_awaken_if_stopped(timeout=self._capture_interval)

    def get_profiling_data(self):
        # type: () -> List[Dict[str, Any]]
        return self._profiling_data

    def _capture_snapshot(self):
        # type: () -> None
        """
        Capture memory usage snapshot.
        """
        capture_time = int(time.time())

        # 1. Capture aggregate values
        all_objects = muppy.get_objects()
        all_objects = self._filter_muppy_objects(all_objects)
        sum1 = summary.summarize(all_objects)
        data = summary.format_(sum1, limit=self._max_items)

        item = {
            "timestamp": capture_time,
            "data": list(data),
            "type": "aggregated",
        }
        self._profiling_data.append(item)

        # 2. Capture diff since the last capture
        data = self._tracker.format_diff()
        item = {
            "timestamp": capture_time,
            "data": list(data),
            "type": "diff",
        }
        self._profiling_data.append(item)

    def _filter_muppy_objects(self, all_objects):
        """
        Remove and filter out objects from the muppy all objects list which we don't want to include
        in the memory profiling data.

        Currently we exclude ourselves to reduce the "observer effect".
        """
        result = []
        for item in all_objects:
            if isinstance(item, dict) and "_profiling_data" in item:
                continue
            elif isinstance(item, PymplerPeriodicMemorySummaryCaptureThread):
                continue
            result.append(item)
        return result


class TracemallocPeriodicMemorySummaryCaptureThread(StoppableThread):
    """
    Thread which periodically captures memory summary using tracemalloc package from Python 3 stdlib.
    """

    def __init__(
        self,
        capture_interval=10,
        max_items=50,
        frames_count=1,
        include_traceback=False,
        ignore_path_globs=None,
        *args,
        **kwargs
    ):
        # type: (int, int, int, bool, Optional[List[six.text_type]], Any, Any) -> None
        """
        :param capture_interval: How often to capture memory usage snapshot.
        :type capture_interval: ``int``
        """
        super(TracemallocPeriodicMemorySummaryCaptureThread, self).__init__(
            name="TracemallocPeriodicMemorySummaryCaptureThread"
        )

        self._capture_interval = capture_interval
        self._max_items = max_items
        self._frames_count = frames_count
        self._include_traceback = include_traceback
        self._ignore_path_globs = ignore_path_globs or []

        self._profiling_data = []  # type: List[Dict[str, Any]]
        self._previous_snapshot = None

    def run_and_propagate(self):
        # type: () -> None
        # NOTE: .start() should be called as soon as possible, but that's not easily possible with
        # our current config and profiling abstraction. In case late start() call results in too
        # much missed profiling data from early start up code, we will need to add new environment
        # variable which calls tracemalloc.start() as early as possible when that env variable is
        # set.
        tracemalloc.start(self._frames_count)

        while self._run_state.is_running():
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Performing periodic memory usage capture using tracemalloc",
            )

            trace_filters_str = ",".join(
                [
                    trace_filter.filename_pattern
                    for trace_filter in self._get_traces_filters()
                ]
            )
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Using tracemalloc trace filters: %s" % (trace_filters_str),
            )
            self._capture_snapshot()
            self._run_state.sleep_but_awaken_if_stopped(timeout=self._capture_interval)

    def stop(self):
        tracemalloc.stop()
        super(TracemallocPeriodicMemorySummaryCaptureThread, self).stop()

    def get_profiling_data(self):
        # type: () -> List[Dict[str, Any]]
        return self._profiling_data

    def _get_traces_filters(self):
        # type: () -> List[tracemalloc.Filter]
        filters = []
        filters.extend(DEFAULT_TRACES_FILTERS)

        for path_glob in self._ignore_path_globs:
            filters.append(tracemalloc.Filter(False, path_glob))

        return filters

    def _capture_snapshot(self):
        # type: () -> None
        """
        Capture memory usage snapshot.
        """
        capture_time = int(time.time())

        traces_filters = self._get_traces_filters()

        # 1. Capture aggregate values
        snapshot = tracemalloc.take_snapshot()
        snapshot = snapshot.filter_traces(traces_filters)

        item = {
            "timestamp": capture_time,
            "data": self._format_snapshot(snapshot),
            "type": "aggregated",
        }
        self._profiling_data.append(item)

        # 2. Capture diff since the last capture
        if self._previous_snapshot:
            item = {
                "timestamp": capture_time,
                "data": self._format_snapshot(snapshot, diff=True),
                "type": "diff",
            }
            self._profiling_data.append(item)

        self._previous_snapshot = snapshot

    def _format_snapshot(self, snapshot, diff=False):
        """
        Format snapshot statistics data in a user-friendly format.
        """
        if diff:
            stats = snapshot.compare_to(self._previous_snapshot, "traceback")[
                : self._max_items
            ]
        else:
            stats = snapshot.statistics("traceback")[: self._max_items]

        result = []
        for index, stat in enumerate(stats, 0):
            frame = stat.traceback[0]

            if diff:
                if stat.size_diff > 0:
                    size_diff_str = "+%s" % (stat.size_diff)
                else:
                    size_diff_str = stat.size_diff

                if stat.count_diff > 0:
                    count_diff_str = "+%s" % (stat.count_diff)
                else:
                    count_diff_str = stat.count_diff

                item = "#%s: %s:%s: %.1f KiB (%s bytes), %d count (%s)" % (
                    index + 1,
                    frame.filename,
                    frame.lineno,
                    stat.size / 1024,
                    size_diff_str,
                    stat.count,
                    count_diff_str,
                )

            else:
                item = "#%s: %s:%s: %.1f KiB, %d count" % (
                    index + 1,
                    frame.filename,
                    frame.lineno,
                    stat.size / 1024,
                    stat.count,
                )

            line = linecache.getline(frame.filename, frame.lineno).strip()

            if line:
                item += "\n\t%s" % (line)

            if self._include_traceback:
                tb = "\n\t".join(stat.traceback.format())
                item += "\n\nTraceback (most recent call first):\n\n%s\b" % (tb)

            result.append(item)

        return result


class MemoryProfiler(BaseProfiler):
    """
    Class for profiling agent memory usage.

    It relies on the "pympler" / "tracemalloc" package. It works by starting a background thread
    which periodically captures memory usage summary.
    """

    def __init__(self, config):
        super(MemoryProfiler, self).__init__(config=config)

        enable_profiling = self.is_profiling_enabled(config=config)

        if enable_profiling:
            if config.memory_profiler not in ["pympler", "tracemalloc"]:
                raise ValueError(
                    "Unsupported memory profiler: %s" % (config.memory_profiler)
                )

            if config.memory_profiler == "pympler" and not pympler:
                global_log.warning(
                    "Profiling is enabled, but the `pympler` module couldn't be loaded. "
                    "You need to install `pympler` in order to use profiling.  This can be done "
                    "via pip:  pip install pympler"
                )
            elif config.memory_profiler == "tracemalloc" and not tracemalloc:
                global_log.warning(
                    "Profiling is enabled, but the `tracemalloc` module couldn't be loaded. "
                    "treacemalloc is only available when using Python >= 3.4 "
                )
            else:
                self._is_available = True

        self._data_file_path = os.path.join(
            config.agent_log_path, config.memory_profile_log_name
        )
        self._capture_interval = 10
        self._max_items = config.memory_profiler_max_items
        self._frames_count = config.memory_profiler_frames_count
        self._include_traceback = config.memory_profiler_include_traceback
        self._ignore_path_globs = config.memory_profiler_ignore_path_globs

        self._running = False
        self._periodic_thread = None

    def is_profiling_enabled(self, config):
        return config.enable_profiling or config.enable_memory_profiling

    def _is_running(self):
        return self._running

    def _start(self, config, current_time):
        if self._running:
            return

        self._running = True

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "Starting memory profiling. Capture interval: %d seconds, duration: %d seconds, max items: %d, number of frames: %d, include traceback: %s"
            % (
                self._capture_interval,
                self._profile_end - self._profile_start,
                self._max_items,
                self._frames_count,
                self._include_traceback,
            ),
        )

        if config.memory_profiler == "pympler":
            periodic_thread_cls = PymplerPeriodicMemorySummaryCaptureThread
        elif config.memory_profiler == "tracemalloc":
            periodic_thread_cls = TracemallocPeriodicMemorySummaryCaptureThread
        else:
            raise ValueError(
                "Unsupported memory profiler: %s" % (config.memory_profiler)
            )

        self._periodic_thread = periodic_thread_cls(
            capture_interval=self._capture_interval,
            max_items=self._max_items,
            frames_count=self._frames_count,
            include_traceback=self._include_traceback,
            ignore_path_globs=self._ignore_path_globs,
            name="MemoryCaptureThread",
        )
        self._periodic_thread.setDaemon(True)
        self._periodic_thread.start()

    def _stop(self, config, current_time):
        if not self._running:
            return

        self._running = False

        global_log.log(scalyr_logging.DEBUG_LEVEL_0, "Stopping memory profiling")

        if not self._periodic_thread:
            return

        profiling_data = self._periodic_thread.get_profiling_data()

        # Stop the periodic capture thread
        self._periodic_thread.stop()
        self._periodic_thread = None

        if os.path.exists(self._data_file_path):
            os.remove(self._data_file_path)

        # Write captured data to log file
        with open(self._data_file_path, "w") as fp:
            for item in profiling_data:
                if item["type"] == "aggregated":
                    type_string = "(aggregated values)"
                elif item["type"] == "diff":
                    type_string = "(diff since the last capture)"
                else:
                    raise ValueError("Invalid type: %s" % (item["type"]))

                line = "timestamp: %s, total lines: %s %s\n%s\n\n" % (
                    item["timestamp"],
                    len(item["data"]),
                    type_string,
                    "\n".join(item["data"]),
                )

                fp.write(line)

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "Memory profiling data written to %s",
            self._data_file_path,
        )

        del profiling_data
