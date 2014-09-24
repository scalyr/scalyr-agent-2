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

__author__ = 'czerwin@scalyr.com'

import os
import re
import scalyr_agent.third_party.tcollector.tcollector as tcollector
from Queue import Empty
from scalyr_agent import ScalyrMonitor, BadMonitorConfiguration
from scalyr_agent.third_party.tcollector.tcollector import ReaderThread
from scalyr_agent.json_lib import JsonObject
from scalyr_agent import StoppableThread

# In this file, we make use of the third party tcollector library.  Much of the machinery here is to
# shoehorn the tcollector code into our framework.

# These are the metrics collected, broken up by tcollector controllor:
# We use the original tcollector documentation here has much as possible.
#
# From procstats:
#   proc.stat.cpu type=*:        CPU counters in units of jiffers, where type can be one of user, nice, system, iowait,
#                                irq, softirq, steal, guest.  As a rate, they should add up to 100*numcpus on the host.
#   proc.stat.intr:              The number of interrupts since boot.
#   proc.stat.ctxt               The number of context switches since boot.
#   proc.stat.processes          The number of processes created since boot.
#   proc.stat.procs_blocked      The number of processes currently blocked on I/O.
#   proc.loadavg.1m              The load average over 1 minute.
#   proc.loadavg.5m              The load average over 5 minutes.
#   proc.loadavg.15m             The load average over 15 minutes.
#   proc.loadavg.runnable        The number of runnable threads/processes.
#   proc.loadavg.total_threads   The total number of threads/processes.
#   proc.kernel.entropy_avail    The number of bits of entropy that can be read without blocking from /dev/random
#   proc.uptime.total            The seconds since boot.
#   proc.uptime.now              The seconds since boot of idle time
#   proc.meminfo.*               Information about memory usage, in counts of 1 KB pages.  The notable categories are:
#                                memtotal (the total amount of RAM), memfree (the total unused RAM),
#                                buffers (the total amount of RAM used by system buffers), cached (the total amount
#                                of RAM used for caching file blocks).  To calculate available memory, you should add
#                                the memfree and cached values together.  See the following link for more details:
#              http://git.kernel.org/cgit/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/proc.txt
#                                for information about the other memory categories.
#   proc.vmstat.pgfault          The number of minor page faults since boot.
#   proc.vmstat.pgmajfault       The number of major page faults since boot
#   proc.vmstat.pswpin           The number of processes swapped in since boot.
#   proc.vmstat.pswpout          The number of processes swapped out since boot.
#   proc.vmstat.pgppin           The number of pages swapped in since boot.
#   proc.vmstat.pgpout           The number of pages swapped out in since boot.
#
#   sys.numa.zoneallocs type=*, node=*
#                                Number of pages allocated from the preferred node, either type=hit or type=miss.
#   sys.numa.foreign_allocs node=*
#                                Number of pages allocated from node because the preferred node did not have any free.
#   sys.numa.allocation node=* type=*
#                                Number of pages allocated either type=locally or type=remotely for processes on this
#                                node.
#   sys.numa.interleave node=* type=hit
#                                The number of pages allocated successfully by the interleave strategy.
#
# Metrics from netstat:
#   net.sockstat.num_sockets     Number of sockets allocated (only TCP).
#   net.sockstat.num_timewait    Number of TCP sockets currently in TIME_WAIT state.
#   net.sockstat.sockets_inuse, type=*
#                                Number of sockets in use by type.
#   net.sockstat.num_orphans     Number of orphan TCP sockets (not attached to any file descriptor).
#   net.sockstat.memory, type=*  Memory allocated for this socket type (in bytes).
#   net.sockstat.ipfragqueues    Number of IP flows for which there are currently fragments queued for reassembly.
#   net.stat.tcp.abort, type=*   Number of connections that the kernel had to abort due broken down by reason.
#   net.stat.tcp.abort.failed    Number of times the kernel failed to abort a connection because it didn't even have
#                                enough memory to reset it.
#   net.stat.tcp.congestion.recovery, type=*
#                                Number of times the kernel detected spurious retransmits and was able to recover part
#                                or all of the CWND, broken down by how it recovered.
#   net.stat.tcp.delayedack, type=*
#                                Number of delayed ACKs sent of different types.
#   net.stat.tcp.failed_accept, reason=*
#                                Number of times a connection had to be dropped  after the 3WHS.  reason=full_acceptq
#                                indicates that the application isn't accepting connections fast enough.  You should
#                                see SYN cookies too.
#   net.stat.tcp.invalid_sack, type=*
#                                Number of invalid SACKs we saw of diff types. (requires Linux v2.6.24-rc1 or newer)
#   net.stat.tcp.memory.pressure Number of times a socket entered the "memory pressure" mode.
#   net.stat.tcp.memory.prune, type=*
#                                Number of times a socket had to discard received data due to low memory conditions,
#                                broken down by type.
#   net.stat.tcp.packetloss.recovery, type=*
#                                Number of times we recovered from packet loss by type of recovery (e.g. fast
#                                retransmit vs SACK).
#   net.stat.tcp.receive.queue.full
#                                Number of times a received packet had to be dropped because the socket's receive
#                                queue was full (requires Linux v2.6.34-rc2 or newer)
#   net.stat.tcp.reording, detectedby=*
#                                Number of times we detected re-ordering broken down by how.
#   net.stat.tcp.syncookies, type=*
#                                SYN cookies (both sent & received).
#
# Metrics from iostat:#
#   iostat.disk.read_requests, dev=*
#                                Number of reads completed by device
#   iostat.disk.read_merged. dev=*
#                                Number of reads merged by device
#   iostat.disk.read_sectors, dev=*
#                                Number of sectors read by device
#   iostat.disk.msec_read, dev=*   Time in msec spent reading by device
#   iostat.disk.write_requests, dev=*
#                                Number of writes completed by device
#   iostat.disk.write_merged, dev=*
#                                Number of writes merged by device
#   iostat.disk.write_sectors, dev=*
#                                Number of sectors written by device
#   iostat.disk.msec_write, dev=* Time in msec spent writing by device
#   iostat.disk.ios_in_progress, dev=*
#                                Number of I/O operations in progress by device
#   iostat.disk.msec_total, dev=*  Time in msec doing I/O by device
#   iostat.disk.msec_weighted_total, dev=*
#                                Weighted time doing I/O (multiplied by ios_in_progress) by device
#
# Note, all of these stats are also published per partition under iostat.partition
#
# Metrics from dfstate:
#   df.1kblocks.total, mount=*, fstype=*
#                              The total size of the file system broken down by mount and filesystem type.
#   df.1kblocks.used, mount=*, fstype=*
#                              The number of blocks used broken down by mount and filesystem type.
#   df.1kblocks.available, mount=*, fstype=*
#                              The number of locks available broken down by mount and filesystem type.
#   df.inodes.total, mount=*, fstype=*
#                              The total number of inodes broken down by mount and filesystem type.
#   df.inodes.used, mount=*, fstype=*
#                              The number of used inodes broken down by mount and filesystem type.
#   df.inodes.free, mount=*, fstype=*
#                              The number of free inodes broken down by mount and filesystem type.
#
# Metrics from ifstat:
#   proc.net.bytes, iface=*, direction=(in|out)
#                              The number of bytes through the interface broken down by interface and direction.
#   proc.net.packets, iface=*, direction=(in|out)
#                              The number of packets through the interface broken down by interface and direction.
#   proc.net.errs, iface=*, direction=(in|out)
#                              The number of packet errors broken down by interface and direction.
#   proc.net.dropped, iface=*, direction=(in|out)
#                              The number of dropped backets broken down by interface and direction.


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
        StoppableThread.__init__(self, name='tcollector writer thread')
        self.__monitor = monitor
        self.__queue = queue
        self.__max_uncaught_exceptions = 100
        self.__logger = logger
        self.__error_logger = error_logger
        self.__timestamp_matcher = re.compile('(\\S+)\\s+\\d+\\s+(.*)')
        self.__key_value_matcher = re.compile('(\\S+)=(\\S+)')

    def __rewrite_tsdb_line(self, line):
        """Rewrites the TSDB line emitted by the collectors to the format used by the agent-metrics parser."""
        # Strip out the timestamp that is the second token on the line.
        match = self.__timestamp_matcher.match(line)
        if match is not None:
            line = '%s %s' % (match.group(1), match.group(2))

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
            except (ArithmeticError, EOFError, EnvironmentError, LookupError,
                    ValueError):
                errors += 1
                if errors > self.__max_uncaught_exceptions:
                    raise
                self.__error_logger.exception('Uncaught exception in SenderThread, ignoring')
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
            self.__queue.put('ignore this')
        StoppableThread.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)


class SystemMetricsMonitor(ScalyrMonitor):
    """A Scalyr agent monitor that records system metrics using tcollector.

    There is no required configuration for this monitor, but there are some options fields you can provide.
    First, you can provide 'tags' whose value should be a dict containing a mapping from tag name to tag value.
    These tags will be added to all metrics reported by monitor.

    The second optional configuration field is 'collectors_directory' which is the path to the directory
    containing the Tcollector collectors to run.  You should not normally have to set this.  It is used for testing.

    TODO:  Document all of the metrics exported this module.
    """

    def _initialize(self):
        """Performs monitor-specific initialization."""
        # Set up tags for this file.
        tags = self._config.get('tags', default=JsonObject())

        if not type(tags) is dict and not type(tags) is JsonObject:
            raise BadMonitorConfiguration('The configuration field \'tags\' is not a dict or JsonObject', 'tags')

        # Make a copy just to be safe.
        tags = JsonObject(content=tags)

        tags['parser'] = 'agent-metrics'

        self.log_config = {
            'attributes': tags,
            'parser': 'agent-metrics',
            'path': 'linux_system_metrics.log',
        }

        collector_directory = self._config.get('collectors_directory', convert_to=str,
                                               default=SystemMetricsMonitor.__get_collectors_directory())

        collector_directory = os.path.realpath(collector_directory)

        if not os.path.isdir(collector_directory):
            raise BadMonitorConfiguration('No such directory for collectors: %s' % collector_directory,
                                          'collectors_directory')

        self.options = TcollectorOptions()
        self.options.cdir = collector_directory

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
        tcollector.main_loop(self.options, self.modules, None, self.tags, False, self._run_state)

        self._logger.debug('Shutting down')

        tcollector.shutdown(invoke_exit=False)
        writer.stop(wait_on_join=False)

        self._logger.debug('Shutting down -- joining the reader thread.')
        reader.join(1)

        self._logger.debug('Shutting down -- joining the writer thread.')
        writer.stop(join_timeout=1)

    @staticmethod
    def __get_collectors_directory():
        """Returns the default location for the tcollector's collectors directory.
        @return: The path to the directory to read the collectors from.
        @rtype: str
        """
        # We determine the collectors directory by looking at the parent directory of where this file resides
        # and then going down third_party/tcollector/collectors.
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir, 'third_party', 'tcollector',
                            'collectors')
