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

from __future__ import absolute_import

import os
import tempfile
import unittest

from io import open

import six
import mock

from scalyr_agent.profiler import ScalyrProfiler
from scalyr_agent.profiler import CPUProfiler
from scalyr_agent.profiler import MemoryProfiler
from scalyr_agent.profiler import PymplerPeriodicMemorySummaryCaptureThread
from scalyr_agent.profiler import TracemallocPeriodicMemorySummaryCaptureThread
from scalyr_agent.util import StoppableThread


def mock_write_profiling_data(file_path, data_type):
    with open(file_path, "w") as fp:
        fp.write(six.text_type(""))


MOCK_YAPPI = mock.Mock()
MOCK_YAPPI.is_running.return_value = True
MOCK_YAPPI.get_func_stats.return_value.save = mock_write_profiling_data

MOCK_PYMPLER = mock.Mock()
MOCK_TRACEMALLOC = mock.Mock()

MOCK_SNAPSHOT = mock.Mock()
MOCK_SNAPSHOT_2 = mock.Mock()
MOCK_SNAPSHOT_2.statistics.return_value = []

MOCK_TRACEMALLOC.take_snapshot.return_value = MOCK_SNAPSHOT
MOCK_SNAPSHOT.filter_tracers.return_value = MOCK_SNAPSHOT_2

MOCK_CONFIG = mock.Mock()
MOCK_CONFIG.enable_profiling = True
MOCK_CONFIG.memory_profiler = "pympler"
MOCK_CONFIG.memory_profiler_max_items = 100
MOCK_CONFIG.memory_profiler_frames_count = 10
MOCK_CONFIG.memory_profiler_include_traceback = False
MOCK_CONFIG.agent_log_path = ""
MOCK_CONFIG.profile_log_name = ""
MOCK_CONFIG.memory_profile_log_name = ""

MOCK_CONFIG_TRACEMALLOC = mock.Mock()
MOCK_CONFIG_TRACEMALLOC.enable_profiling = True
MOCK_CONFIG_TRACEMALLOC.memory_profiler = "tracemalloc"
MOCK_CONFIG_TRACEMALLOC.memory_profiler_max_items = 100
MOCK_CONFIG_TRACEMALLOC.memory_profiler_frames_count = 10
MOCK_CONFIG_TRACEMALLOC.memory_profiler_include_traceback = False
MOCK_CONFIG_TRACEMALLOC.agent_log_path = ""
MOCK_CONFIG_TRACEMALLOC.profile_log_name = ""
MOCK_CONFIG_TRACEMALLOC.memory_profile_log_name = ""


class BaseMockPeriodicMemorySummaryCaptureThread(object):
    _profiling_data = [{"type": "aggregated", "timestamp": 1, "data": ["a", "b"]}]

    def __init__(self, capture_interval=10, *args, **kwargs):
        StoppableThread.__init__(self)

    def run_and_propagate(self):
        pass

    def stop(self):
        pass

    def _capture_snapshot(self):
        pass


class PymplerMockPeriodicMemorySummaryCaptureThread(
    BaseMockPeriodicMemorySummaryCaptureThread,
    PymplerPeriodicMemorySummaryCaptureThread,
):
    pass


class TracemallocMockPeriodicMemorySummaryCaptureThread(
    BaseMockPeriodicMemorySummaryCaptureThread,
    TracemallocPeriodicMemorySummaryCaptureThread,
):
    pass


class ScalyrProfilerTestCase(unittest.TestCase):
    def test_update_profiling_disabled(self):
        MOCK_CONFIG.enable_profiling = False

        profiler = ScalyrProfiler(config=MOCK_CONFIG)
        # Should result in no-op if profiling is disabled
        profiler.update(MOCK_CONFIG)

    @mock.patch("scalyr_agent.profiler.yappi", None)
    @mock.patch("scalyr_agent.profiler.pympler", None)
    def test_update_profiling_enabled_profiler_module_not_available(self):
        # Should result in no-op if profiling is enabled, but profiling modules are not available
        MOCK_CONFIG.enable_profiling = True

        profiler = ScalyrProfiler(config=MOCK_CONFIG)
        # Should result in no-op if profiling is disabled
        profiler.update(MOCK_CONFIG)


class CPUProfilerTestCase(unittest.TestCase):
    def test_is_profiling_enabled(self):
        MOCK_CONFIG.enable_profiling = True
        MOCK_CONFIG.enable_cpu_profiling = False

        profiler = CPUProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG))

        MOCK_CONFIG.enable_profiling = False
        MOCK_CONFIG.enable_cpu_profiling = True

        profiler = CPUProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG))

        MOCK_CONFIG.enable_profiling = False
        MOCK_CONFIG.enable_cpu_profiling = False

        profiler = CPUProfiler(config=MOCK_CONFIG)
        self.assertFalse(profiler.is_profiling_enabled(config=MOCK_CONFIG))

    @mock.patch("scalyr_agent.profiler.yappi", None)
    def test_is_running_yappi_module_not_available(self):
        MOCK_CONFIG.enable_profiling = True

        profiler = CPUProfiler(config=MOCK_CONFIG)
        self.assertFalse(profiler._is_available)
        self.assertFalse(profiler._is_running())

    @mock.patch("scalyr_agent.profiler.yappi", MOCK_YAPPI)
    def test_is_running_yappi_module_available(self):
        MOCK_CONFIG.enable_profiling = True

        profiler = CPUProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler._is_available)
        self.assertTrue(profiler._is_running())

    @mock.patch("scalyr_agent.profiler.yappi", MOCK_YAPPI)
    def test_profiling_data_is_written_on_stop(self):
        data_file_fd, data_file_path = tempfile.mkstemp()

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(data_file_fd)

        MOCK_CONFIG.enable_profiling = True
        MOCK_CONFIG.profile_log_name = data_file_path

        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertTrue(is_file_path_empty(data_file_path))

        profiler = CPUProfiler(config=MOCK_CONFIG)
        profiler._data_file_path = data_file_path

        try:
            profiler._start(MOCK_CONFIG, None)
        finally:
            profiler._stop(MOCK_CONFIG, None)

        # Verify data is written on _stop method call
        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertFalse(is_file_path_empty(data_file_path))


class PymplerMemoryProfilerTestCase(unittest.TestCase):
    def test_is_profiling_enabled(self):
        MOCK_CONFIG.enable_profiling = True
        MOCK_CONFIG.enable_memory_profiling = False

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG))

        MOCK_CONFIG.enable_profiling = False
        MOCK_CONFIG.enable_memory_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG))

        MOCK_CONFIG.enable_profiling = False
        MOCK_CONFIG.enable_memory_profiling = False

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertFalse(profiler.is_profiling_enabled(config=MOCK_CONFIG))

    @mock.patch("scalyr_agent.profiler.pympler", None)
    def test_is_running_pympler_module_not_available(self):
        MOCK_CONFIG.enable_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertFalse(profiler._is_available)
        self.assertFalse(profiler._is_running())

    @mock.patch("scalyr_agent.profiler.pympler", MOCK_PYMPLER)
    def test_is_running_yappi_module_available(self):
        MOCK_CONFIG.enable_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler._is_available)
        self.assertFalse(profiler._is_running())

    @mock.patch(
        "scalyr_agent.profiler.PymplerPeriodicMemorySummaryCaptureThread",
        PymplerMockPeriodicMemorySummaryCaptureThread,
    )
    @mock.patch("scalyr_agent.profiler.pympler", MOCK_PYMPLER)
    def test_profiling_data_is_written_on_stop(self):
        # Verify data is written on _stop method call
        data_file_fd, data_file_path = tempfile.mkstemp()

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(data_file_fd)

        MOCK_CONFIG.enable_profiling = True
        MOCK_CONFIG.memory_profile_log_name = data_file_path

        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertTrue(is_file_path_empty(data_file_path))

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler._is_available)
        self.assertFalse(profiler._is_running())

        try:
            profiler._start(MOCK_CONFIG, None)
            self.assertTrue(profiler._is_running())
        finally:
            profiler._stop(MOCK_CONFIG, None)

        self.assertFalse(profiler._is_running())

        # Verify data is written on _stop method call
        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertFalse(is_file_path_empty(data_file_path))


class TracemallocMemoryProfilerTestCase(unittest.TestCase):
    def test_is_profiling_enabled(self):
        MOCK_CONFIG_TRACEMALLOC.enable_profiling = True
        MOCK_CONFIG_TRACEMALLOC.enable_memory_profiling = False

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG_TRACEMALLOC))

        MOCK_CONFIG_TRACEMALLOC.enable_profiling = False
        MOCK_CONFIG_TRACEMALLOC.enable_memory_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertTrue(profiler.is_profiling_enabled(config=MOCK_CONFIG_TRACEMALLOC))

        MOCK_CONFIG_TRACEMALLOC.enable_profiling = False
        MOCK_CONFIG_TRACEMALLOC.enable_memory_profiling = False

        profiler = MemoryProfiler(config=MOCK_CONFIG)
        self.assertFalse(profiler.is_profiling_enabled(config=MOCK_CONFIG_TRACEMALLOC))

    @mock.patch("scalyr_agent.profiler.tracemalloc", None)
    def test_is_running_pympler_module_not_available(self):
        MOCK_CONFIG_TRACEMALLOC.enable_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG_TRACEMALLOC)
        self.assertFalse(profiler._is_available)
        self.assertFalse(profiler._is_running())

    @mock.patch("scalyr_agent.profiler.tracemalloc", MOCK_TRACEMALLOC)
    def test_is_running_yappi_module_available(self):
        MOCK_CONFIG_TRACEMALLOC.enable_profiling = True

        profiler = MemoryProfiler(config=MOCK_CONFIG_TRACEMALLOC)
        self.assertTrue(profiler._is_available)
        self.assertFalse(profiler._is_running())

    @mock.patch(
        "scalyr_agent.profiler.TracemallocPeriodicMemorySummaryCaptureThread",
        TracemallocMockPeriodicMemorySummaryCaptureThread,
    )
    @mock.patch("scalyr_agent.profiler.tracemalloc", MOCK_TRACEMALLOC)
    def test_profiling_data_is_written_on_stop(self):
        # Verify data is written on _stop method call
        data_file_fd, data_file_path = tempfile.mkstemp()

        # NOTE: We close the fd here because we open it again below. This way file deletion at
        # the end works correctly on Windows.
        os.close(data_file_fd)

        MOCK_CONFIG_TRACEMALLOC.enable_profiling = True
        MOCK_CONFIG_TRACEMALLOC.memory_profile_log_name = data_file_path

        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertTrue(is_file_path_empty(data_file_path))

        profiler = MemoryProfiler(config=MOCK_CONFIG_TRACEMALLOC)
        self.assertTrue(profiler._is_available)
        self.assertFalse(profiler._is_running())

        try:
            profiler._start(MOCK_CONFIG_TRACEMALLOC, None)
            self.assertTrue(profiler._is_running())
        finally:
            profiler._stop(MOCK_CONFIG_TRACEMALLOC, None)

        self.assertFalse(profiler._is_running())

        # Verify data is written on _stop method call
        self.assertTrue(
            os.path.isfile(data_file_path), "File %s doesn't exist" % (data_file_path)
        )
        self.assertFalse(is_file_path_empty(data_file_path))


def is_file_path_empty(file_path):
    # type: (str) -> bool
    """
    Return true if the provided file path is empty.
    """
    return os.path.getsize(file_path) == 0
