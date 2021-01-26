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

"""
This module contains platform agnostic system and process metrics collectors.
"""

from __future__ import absolute_import

import time

try:
    import psutil
except ImportError:
    psutil = None
    raise ImportError(
        'You must install the python module "psutil". Typically, this can be done with'
        "the following command: pip install psutil"
    )


from scalyr_agent.builtin_monitors.linux_process_metrics import Metric

__all__ = ["PSUtilProcessTracker"]


class PSUtilProcessTracker(object):
    """
    Process tracker which captures metrics using psutil library which means it works across
    different platforms (Linux, Windows, FreeBSD, OS X).

    Currently it only supports the following metrics which are utilized by CodeSpeed benchmarks.

        - app.cpu type=user
        - app.cpu type=system
        - app.uptime
        - app.threads

        - app.mem.bytes type=resident
        - app.mem.bytes type=vmsize

        - app.disk.requests type=read
        - app.disk.requests type=write
        - app.disk.bytes type=read
        - app.disk.bytes type=write

        - app.io.wait

    NOTE: The following metrics are Unix specific so they are not included:

        - app.nice
    """

    def __init__(self, pid, logger, monitor_id=None):
        self.pid = pid
        self.monitor_id = monitor_id
        self._logger = logger

    def collect(self):
        result = {}

        process = psutil.Process(self.pid)

        with process.oneshot():
            cpu_times = process.cpu_times()
            memory_info = process.memory_info()
            memory_maps = process.memory_maps()
            io_counters = process.io_counters()
            threads = process.threads()
            create_time = process.create_time()

        now = int(time.time())
        uptime_ms = int(now - create_time) * 1000

        # CPU related metrics
        # psutil returns seconds, but original ProcessMetrics returns in jiffies aka 1/100th of
        # a second and that's why we need to convert the value here
        result[Metric("app.cpu", "user")] = round(cpu_times.user * 100)
        result[Metric("app.cpu", "system")] = round(cpu_times.system * 100)
        result[Metric("app.uptime", None)] = uptime_ms
        result[Metric("app.threads", None)] = len(threads)

        # Memory related metrics
        result[Metric("app.mem.bytes", "resident")] = memory_info.rss
        result[Metric("app.mem.bytes", "vmsize")] = memory_info.vms

        # Custom metrics only available via psutil
        memory_resident_shared, memory_resident_private = 0, 0
        for memory_map in memory_maps:
            memory_resident_shared += memory_map.shared_clean + memory_map.shared_dirty
            memory_resident_private += (
                memory_map.private_clean + memory_map.private_dirty
            )

        result[Metric("app.mem.bytes", "resident_shared")] = memory_resident_shared
        result[Metric("app.mem.bytes", "resident_private")] = memory_resident_private

        # Disk metrics
        result[Metric("app.disk.requests", "read")] = io_counters.read_count
        result[Metric("app.disk.requests", "write")] = io_counters.write_count
        result[Metric("app.disk.bytes", "read")] = io_counters.read_bytes
        result[Metric("app.disk.bytes", "write")] = io_counters.write_bytes

        # I/O metrics
        # It returns seconds, but we want 1/100th of a second for consistency
        io_wait = int(cpu_times.iowait * 100)
        result[Metric("app.io.wait", None)] = io_wait

        return result
