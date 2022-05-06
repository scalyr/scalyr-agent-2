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
# author:  Steven Czerwinski <czerwin@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

if False:
    from typing import List


__author__ = "czerwin@scalyr.com"


import os
import re

import six
from six.moves.queue import Empty

import scalyr_agent.third_party.tcollector.tcollector as tcollector

from scalyr_agent import (
    ScalyrMonitor,
    BadMonitorConfiguration,
    define_metric,
    define_log_field,
    define_config_option,
)
from scalyr_agent.third_party.tcollector.tcollector import ReaderThread
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent import StoppableThread

# In this file, we make use of the third party tcollector library.  Much of the machinery here is to
# shoehorn the tcollector code into our framework.

__monitor__ = __name__

# These are the metrics collected, broken up by tcollector controllor:
# We use the original tcollector documentation here has much as possible.
define_metric(
    __monitor__, "sys.cpu.count", "Number of CPUs on the host.", category="General"
)

define_metric(
    __monitor__,
    "proc.stat.cpu",
    "CPU counters in units of jiffies, by `type`. Type can be `user`, `nice`, `system`, "
    "`iowait`, `irq`, `softirq`, `steal`, or `guest`. Values are cumulative since boot. "
    "You can run the command `getconf CLK_TCK` to ascertain the time span of a jiffy. "
    "Typically, the return will be `100`; the counter increments 100x a second, and one "
    "jiffy is 10 ms. As a rate, the `type` values should add up to `100*numcpus` on the host. "
    "This PowerQuery will calculate the mean rate of one-minute intervals, over a one hour time "
    "span: `metric = 'proc.stat.cpu' serverHost = 'your-server-name' value > 0 | group ct=count(), "
    "rate = (max(value) - min(value))/60 by type, timebucket('1m') | filter ct == 2 | group mean(rate) "
    "by type`. Note: we sample metrics twice a minute; filtering for `ct == 2` eliminates noise, "
    "caused by jitter.",
    extra_fields={"type": ""},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.stat.intr",
    "Number of interrupts. The value is cumulative since boot.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.stat.ctxt",
    "Number of context switches. The value is cumulative since boot.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.stat.processes",
    "Number of processes created. The value is cumulative since boot.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.stat.procs_blocked",
    "Number of processes currently blocked on I/O.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.loadavg.1min",
    "Load average over 1 minute.",
    category="General",
)
define_metric(
    __monitor__,
    "proc.loadavg.5min",
    "Load average over 5 minutes.",
    category="General",
)
define_metric(
    __monitor__,
    "proc.loadavg.15min",
    "Load average over 15 minutes.",
    category="General",
)
define_metric(
    __monitor__,
    "proc.loadavg.runnable",
    "Number of runnable threads/processes.",
    category="General",
)
define_metric(
    __monitor__,
    "proc.loadavg.total_threads",
    "Number of threads/processes.",
    category="General",
)
define_metric(
    __monitor__,
    "proc.kernel.entropy_avail",
    "Bits of entropy that can be read without blocking from `/dev/random`.",
    unit="bits",
    category="General",
)
define_metric(
    __monitor__,
    "proc.uptime.total",
    "Seconds since boot.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "proc.uptime.now",
    "Seconds of idle time. The value is cumulative since boot.",
    unit="seconds",
    cumulative=True,
    category="General",
)

define_metric(
    __monitor__,
    "proc.vmstat.pgfault",
    "Number of minor page faults. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)
define_metric(
    __monitor__,
    "proc.vmstat.pgmajfault",
    "Number of major page faults. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)
define_metric(
    __monitor__,
    "proc.vmstat.pswpin",
    "Number of processes swapped in. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)
define_metric(
    __monitor__,
    "proc.vmstat.pswpout",
    "Number of processes swapped out. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)
define_metric(
    __monitor__,
    "proc.vmstat.pgpgin",
    "Number of pages swapped in. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)
define_metric(
    __monitor__,
    "proc.vmstat.pgpgout",
    "Number of pages swapped out. The value is cumulative since boot.",
    cumulative=True,
    category="Virtual Memory",
)

define_metric(
    __monitor__,
    "sys.numa.zoneallocs",
    "Number of pages allocated on the node, by `node` and `type`. The value is "
    "cumulative since boot. Type is either `hit` "
    "(memory was successfully allocated on the intended node); or `miss` "
    "(memory was allocated on the node, despite the preference for a different node).",
    extra_fields={"node": "", "type": ""},
    category="NUMA",
)
define_metric(
    __monitor__,
    "sys.numa.foreign_allocs",
    "Number of pages allocated on the node because the preferred node had none "
    "free, by `node`. The value is cumulative since boot. Each increment also "
    "has a `type='miss'` increment for a different node in `sys.numa.zoneallocs`.",
    extra_fields={"node": ""},
    category="NUMA",
)
define_metric(
    __monitor__,
    "sys.numa.allocation",
    "Number of pages allocated, by `node` and `type`. The value is cumulative since "
    "boot. Type is either 'locally', or 'remotely', for processes on this node.",
    extra_fields={"node": "", "type": ""},
    category="NUMA",
)
define_metric(
    __monitor__,
    "sys.numa.interleave",
    "Number of pages successfully allocated by the interleave strategy. "
    "The value is cumulative since boot.",
    extra_fields={"node": "", "type": "hit"},
    category="NUMA",
)


define_metric(
    __monitor__,
    "net.sockstat.num_sockets",
    "Number of sockets allocated (only TCP).",
    category="Sockets",
)
define_metric(
    __monitor__,
    "net.sockstat.num_timewait",
    "Number of TCP sockets currently in TIME_WAIT state.",
    category="Sockets",
)
define_metric(
    __monitor__,
    "net.sockstat.sockets_inuse",
    "Number of sockets in use, by `type` (e.g. `tcp`, `udp`, `raw`, etc.).",
    extra_fields={"type": ""},
    category="Sockets",
)
define_metric(
    __monitor__,
    "net.sockstat.num_orphans",
    "Number of orphan TCP sockets (not attached to any file descriptor).",
    category="Sockets",
)
define_metric(
    __monitor__,
    "net.sockstat.memory",
    "Bytes allocated, by socket `type`.",
    extra_fields={"type": ""},
    unit="bytes",
    category="Sockets",
)
define_metric(
    __monitor__,
    "net.sockstat.ipfragqueues",
    "Number of IP flows for which there are currently fragments queued for reassembly.",
    category="Sockets",
)

define_metric(
    __monitor__,
    "net.stat.tcp.abort",
    "Number of connections aborted by the kernel, by `type`. The value is cumulative since boot. See the "
    "[tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/"
    "37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L191) for `type` definitions. "
    "`type='out_of_memory'` is especially bad; the kernel dropped a connection due to too many "
    "orphaned sockets. Other types are normal (e.g. `type='timeout'`).",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.abort.failed",
    "Number of times the kernel failed to abort a connection because it did not "
    "have enough memory to reset it. The value is cumulative since boot.",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.congestion.recovery",
    "Number of times the kernel detected spurious retransmits, and recovered all or "
    "part of the CWND, by `type`. The value is cumulative since boot. See the "
    "[tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/"
    "37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L179) for "
    "`type` definitions.",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.delayedack",
    "Number of delayed ACKs sent, by `type`. The value is cumulative since boot. "
    "See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/"
    "37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L141) for "
    "`type` definitions.",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.failed_accept",
    "Number of connections dropped after the 3WHS, by `reason`. The value is "
    "cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/"
    "tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L150) "
    "for `reason` definitions. A reason of `full_acceptq` indicates the application is not "
    "accepting connections fast enough; also check your SYN cookies.",
    extra_fields={"reason": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.invalid_sack",
    "Number of invalid SACKs, by `type`. The value is cumulative since boot. See the "
    "[tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/"
    "37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L215) for "
    "`type` definitions. (This metric requires Linux v2.6.24-rc1 or newer.)",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.memory.pressure",
    'Number of times a socket entered the "memory pressure" mode. '
    "The value is cumulative since boot.",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.memory.prune",
    "Number of times a socket discarded received data, due to low memory "
    "conditions, by `type`. The value is cumulative since boot. See the "
    "[tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/"
    "37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L134) "
    "for `type` definitions.",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.packetloss.recovery",
    "Number of recoveries from packet loss, by `type` of recovery. The value is "
    "cumulative since boot. See the [tcollector documentation](https://github.com"
    "/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/"
    "0/netstat.py#L134) for `type` definitions.",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.receive.queue.full",
    "Number of times a received packet was dropped because the socket's "
    "receive queue was full. The value is cumulative since boot. "
    "(This metric requires Linux v2.6.34-rc2 or newer.)",
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.reording",
    "Number of times we detected re-ordering, by `detectedby`. The value "
    "is cumulative since boot. See the [tcollector documentation](https://"
    "github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14"
    "/collectors/0/netstat.py#L169) for `detectedby` definitions.",
    extra_fields={"detectedby": ""},
    cumulative=True,
    category="Network",
)
define_metric(
    __monitor__,
    "net.stat.tcp.syncookies",
    "Number of SYN cookies (both sent & received), by `type`. The value is "
    "cumulative since boot. See the [tcollector documentation](https://"
    "github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14"
    "/collectors/0/netstat.py#L126) for `type` definitions.",
    extra_fields={"type": ""},
    cumulative=True,
    category="Network",
)

define_metric(
    __monitor__,
    "iostat.disk.read_requests",
    "Number of reads completed, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.read_merged",
    "Number of reads merged, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.read_sectors",
    "Number of sectors read, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.msec_read",
    "Milliseconds spent reading, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    unit="milliseconds",
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.write_requests",
    "Number of completed writes, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.write_merged",
    "Number of writes merged, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.write_sectors",
    "Number of sectors written, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.msec_write",
    "Milliseconds spent writing, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    unit="milliseconds",
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.ios_in_progress",
    "Number of I/O operations in progress, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.msec_total",
    "Milliseconds performing I/O, by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    unit="milliseconds",
    cumulative=True,
    category="Disk Requests",
)
define_metric(
    __monitor__,
    "iostat.disk.msec_weighted_total",
    "Weighted total: milliseconds performing I/O multiplied by `ios_in_progress`, "
    "by device (`dev`). The value is cumulative since boot.",
    extra_fields={"dev": ""},
    unit="milliseconds",
    cumulative=True,
    category="Disk Requests",
)

define_metric(
    __monitor__,
    "df.1kblocks.total",
    "Size of the file system in 1 kB blocks, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    unit="bytes:1024",
    category="Disk Resources",
)
define_metric(
    __monitor__,
    "df.1kblocks.used",
    "Number of 1 kB blocks used, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    unit="bytes:1024",
    category="Disk Resources",
)
define_metric(
    __monitor__,
    "df.1kblocks.free",
    "Number of 1 kB blocks free, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    unit="bytes:1024",
    category="Disk Resources",
)
define_metric(
    __monitor__,
    "df.inodes.total",
    "Number of inodes, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    category="Disk Resources",
)
define_metric(
    __monitor__,
    "df.inodes.used",
    "Number of used inodes, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    category="Disk Resources",
)
define_metric(
    __monitor__,
    "df.inodes.free",
    "Number of free inodes, by mount and filesystem type.",
    extra_fields={"mount": "", "fstype": ""},
    category="Disk Resources",
)

define_metric(
    __monitor__,
    "proc.meminfo.memtotal",
    "Number of 1 kB pages of RAM.",
    unit="bytes:1024",
    category="Memory",
)
define_metric(
    __monitor__,
    "proc.meminfo.memfree",
    "Number of unused 1 kB pages of RAM. This does not include cached pages, "
    "which can be used to allocate memory as needed.",
    unit="bytes:1024",
    category="Memory",
)
define_metric(
    __monitor__,
    "proc.meminfo.cached",
    "Number of 1 kB pages of RAM used to cache blocks from the filesystem. "
    "These can be used to allocate memory as needed.",
    unit="bytes:1024",
    category="Memory",
)
define_metric(
    __monitor__,
    "proc.meminfo.buffers",
    "Number of 1 KB pages of RAM being used in system buffers.",
    unit="bytes:1024",
    category="Memory",
)

define_log_field(__monitor__, "monitor", "Always `linux_system_metrics`.")
define_log_field(
    __monitor__,
    "metric",
    'Name of the metric, e.g. "proc.stat.cpu". Some metrics have additional '
    "fields; see the [Metrics Reference](#metrics).",
)
define_log_field(__monitor__, "value", "Value of the metric.")

define_config_option(
    __monitor__,
    "network_interface_prefixes",
    "Optional (defaults to `eth`). A string, or a list of strings, specifying "
    "network interface prefixes. The prefix must be the full string after `/dev/`. "
    "For example, `eth` matches all devices starting with `/dev/eth`, and matches "
    'network interfaces named "eth0", "eth1", "ethA", "ethB", etc.',
)
define_config_option(
    __monitor__,
    "network_interface_suffix",
    "Optional (defaults to `[0-9A-Z]+`). Suffix for the network interfaces. "
    "This is a single regular expression, appended to each of the "
    "`network_interface_prefixes`, to create the full interface name.",
)

define_config_option(
    __monitor__,
    "local_disks_only",
    "Optional (defaults to `true`). Limits metric collection to locally mounted filesystems.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "ignore_mounts",
    "List of glob patterns for mounts to ignore. Defaults to "
    '`["/sys/*", "/dev*", "/run*", "/var/lib/docker/*", "/snap/*"]`; typically these '
    "are special docker, cgroup, and other related mount points. "
    "To include them, set an `[]` empty list.",
    convert_to=ArrayOfStrings,
    default=["/sys/*", "/dev*", "/run*", "/var/lib/docker/*", "/snap/*"],
)


class TcollectorOptions(object):
    """Bare minimum implementation of an object to represent the tcollector options.

    We require this to pass into tcollector to control how it is run.
    """

    def __init__(self):
        # The collector directory.
        self.cdir = None
        # An option we created to prevent the tcollector code from failing on fatal in certain locations.
        # Instead, an exception will be thrown.
        self.no_fatal_on_error = True
        # A list of the prefixes for network interfaces to report.  Usually defaults to ["eth"]
        self.network_interface_prefixes = None
        # A regex applied as a suffix to the network_interface_prefixes.  Defaults to '[0-9A-Z]+'
        self.network_interface_suffix = None
        # Whether or not to limit the metrics to only locally mounted filesystems.
        self.local_disks_only = True
        # A list of glob patterns for mounts to ignore
        self.ignore_mounts = []  # type: List[str]


class WriterThread(StoppableThread):
    """A thread that pulls lines off of a reader thread and writes them to the log.  This is needed
    to replace tcollector's SenderThread which sent the lines to a tsdb server.  Instead, we write them
    to our log file.
    """

    def __init__(self, monitor, queue, logger, error_logger):
        """Initializes the instance.

        @param monitor: The monitor instance associated with this tcollector.
        @param queue: The Queue of lines (strings) that are pending to be written to the log. These should come from
            the ReaderThread as it reads and transforms the data from the running collectors.
        @param logger: The Logger to use to report metric values.
        @param error_logger: The Logger to use to report diagnostic information about the running of the monitor.
        """
        StoppableThread.__init__(self, name="tcollector writer thread")
        self.__monitor = monitor
        self.__queue = queue
        self.__max_uncaught_exceptions = 100
        self.__logger = logger
        self.__error_logger = error_logger
        self.__timestamp_matcher = re.compile("(\\S+)\\s+\\d+\\s+(.*)")
        self.__key_value_matcher = re.compile("(\\S+)=(\\S+)")

    def __rewrite_tsdb_line(self, line):
        """Rewrites the TSDB line emitted by the collectors to the format used by the agent-metrics parser."""
        # Strip out the timestamp that is the second token on the line.
        match = self.__timestamp_matcher.match(line)
        if match is not None:
            line = "%s %s" % (match.group(1), match.group(2))

        # Now rewrite any key/value pairs from foo=bar to foo="bar"
        line = self.__key_value_matcher.sub('\\1="\\2"', line)
        return line

    def run(self):
        errors = 0  # How many uncaught exceptions in a row we got.
        while self._run_state.is_running():
            try:
                try:
                    line = self.__rewrite_tsdb_line(self.__queue.get(True, 5))
                except Empty:
                    continue
                # It is important that we check is_running before we act upon any element
                # returned by the queue.  See the 'stop' method for details.
                if not self._run_state.is_running():
                    continue
                self.__logger.info(line, metric_log_for_monitor=self.__monitor)
                while True:
                    try:
                        line = self.__rewrite_tsdb_line(self.__queue.get(False))
                    except Empty:
                        break
                    if not self._run_state.is_running():
                        continue
                    self.__logger.info(line, metric_log_for_monitor=self.__monitor)

                errors = 0  # We managed to do a successful iteration.
            except (
                ArithmeticError,
                EOFError,
                EnvironmentError,
                LookupError,
                ValueError,
            ):
                errors += 1
                if errors > self.__max_uncaught_exceptions:
                    raise
                self.__error_logger.exception(
                    "Uncaught exception in SenderThread, ignoring"
                )
                self._run_state.sleep_but_awaken_if_stopped(1)
                continue

    def stop(self, wait_on_join=True, join_timeout=5):
        """Stops the thread from running.

        By default, this will also block until the thread has completed (by performing a join).

        @param wait_on_join: If True, will block on a join of this thread.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        # We override this method to take some special care to ensure the reader thread will stop quickly as well.
        self._run_state.stop()
        # This thread may be blocking on self.__queue.get, so we add a fake entry to the
        # queue to get it to return.  Since we set run_state to stop before we do this, and we always
        # check run_state before acting on an element from queue, it should be ignored.
        if self._run_state.is_running():
            self.__queue.put("ignore this")
        StoppableThread.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)


class SystemMetricsMonitor(
    ScalyrMonitor
):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    r"""
# Linux System Metrics

Import CPU consumption, memory usage, and other metrics for a Linux server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Linux server.


2\. Set configuration options

This plugin is automatically configured on Agent installation. There are a few [Configuration Options](#options) you may wish to set:
- By default this plugin collects statistics from network interfaces prefixed `eth`, followed by a suffix matching the regular expression `[0-9A-Z]+`. You can set a list of prefixes, and a regular expression for the suffix.
- You can set a list of glob patterns for mounts to ignore. The default configuration ignores `/sys/*`, `/dev*`, `/run*`, `/var/lib/docker/*`, and `/snap/*`. Typically these are special docker, cgroup, and other related mount points.
- You can expand metric collection beyond the locally mounted filesystems.

To set an option, open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`. Find the `monitors: [ ... ]` section and the `{...}` stanza for Linux system metrics:

    monitors: [
      {
         module:            "scalyr_agent.builtin_monitors.linux_system_metrics",
      }
    ]

Add configuration options to the `{...}` stanza, then save the `agent.json` file. The Agent will detect changes within 30 seconds.


3\. Confirm

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > system. You will see an overview of Linux system metrics, across all Linux servers running the Scalyr Agent. The dashboard only shows some of the data collected. Go to Search view and query [monitor = 'linux_system_metrics'](/events?filter=monitor+%3D+%27linux_system_metrics%27) to view all data.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).

    """
    # fmt: on

    def _initialize(self):
        """Performs monitor-specific initialization."""
        # Set up tags for this file.
        tags = self._config.get("tags", default=JsonObject())

        if type(tags) is not dict and type(tags) is not JsonObject:
            raise BadMonitorConfiguration(
                "The configuration field 'tags' is not a dict or JsonObject", "tags"
            )

        # Make a copy just to be safe.
        tags = JsonObject(content=tags)

        tags["parser"] = "agent-metrics"

        self.log_config = {
            "attributes": tags,
            "parser": "agent-metrics",
            "path": "linux_system_metrics.log",
        }

        collector_directory = self._config.get(
            "collectors_directory",
            convert_to=six.text_type,
            default=SystemMetricsMonitor.__get_collectors_directory(),
        )

        collector_directory = os.path.realpath(collector_directory)

        if not os.path.isdir(collector_directory):
            raise BadMonitorConfiguration(
                "No such directory for collectors: %s" % collector_directory,
                "collectors_directory",
            )

        self.options = TcollectorOptions()
        self.options.cdir = collector_directory

        self.options.network_interface_prefixes = self._config.get(
            "network_interface_prefixes", default="eth"
        )
        if isinstance(self.options.network_interface_prefixes, six.string_types):
            self.options.network_interface_prefixes = [
                self.options.network_interface_prefixes
            ]

        self.options.network_interface_suffix = self._config.get(
            "network_interface_suffix", default="[0-9A-Z]+"
        )
        self.options.local_disks_only = self._config.get("local_disks_only")

        if self._config.get("ignore_mounts"):
            if isinstance(self._config.get("ignore_mounts"), ArrayOfStrings):
                self.options.ignore_mounts = self._config.get("ignore_mounts")._items
            else:
                self.options.ignore_mounts = self._config.get("ignore_mounts")
        else:
            self.options.ignore_mounts = []

        self.modules = tcollector.load_etc_dir(self.options, tags)
        self.tags = tags

    def run(self):
        """Begins executing the monitor, writing metric output to self._logger."""
        tcollector.override_logging(self._logger)
        tcollector.reset_for_new_run()

        # At this point we're ready to start processing, so start the ReaderThread
        # so we can have it running and pulling in data from reading the stdins of all the collectors
        # that will be soon running.
        reader = ReaderThread(0, 300, self._run_state)
        reader.start()

        # Start the writer thread that grabs lines off of the reader thread's queue and emits
        # them to the log.
        writer = WriterThread(self, reader.readerq, self._logger, self._logger)
        writer.start()

        # Now run the main loop which will constantly watch the collector module files, reloading / spawning
        # collectors as necessary.  This should only terminate once is_stopped becomes true.
        tcollector.main_loop(
            self.options,
            self.modules,
            None,
            self.tags,
            False,
            self._run_state,
            self._sample_interval_secs,
        )

        self._logger.debug("Shutting down")

        tcollector.shutdown(invoke_exit=False)
        writer.stop(wait_on_join=False)

        self._logger.debug("Shutting down -- joining the reader thread.")
        reader.join(1)

        self._logger.debug("Shutting down -- joining the writer thread.")
        writer.stop(join_timeout=1)

    @staticmethod
    def __get_collectors_directory():
        """Returns the default location for the tcollector's collectors directory.
        @return: The path to the directory to read the collectors from.
        @rtype: str
        """
        # We determine the collectors directory by looking at the parent directory of where this file resides
        # and then going down third_party/tcollector/collectors.
        # TODO: Fix this so it works on the Windows agent.  We need to depend on the tcollectors.. but since this
        # is a Linux specific module, we don't do anything for it.
        return os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            os.path.pardir,
            "third_party",
            "tcollector",
            "collectors",
        )
