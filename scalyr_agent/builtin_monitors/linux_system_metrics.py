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
from scalyr_agent import ScalyrMonitor, BadMonitorConfiguration, define_metric, define_log_field, define_config_option
from scalyr_agent.third_party.tcollector.tcollector import ReaderThread
from scalyr_agent.json_lib import JsonObject
from scalyr_agent import StoppableThread

# In this file, we make use of the third party tcollector library.  Much of the machinery here is to
# shoehorn the tcollector code into our framework.

__monitor__ = __name__

# These are the metrics collected, broken up by tcollector controllor:
# We use the original tcollector documentation here has much as possible.
define_metric(__monitor__, 'cpu.count',
              'The number of CPUs on the system', category='general')

define_metric(__monitor__, 'proc.stat.cpu',
              'CPU counters in units of jiffies, where ``type`` can be one of ``user``, ``nice``, ``system``,  '
              '``iowait``, ``irq``, ``softirq``, ``steal``, ``guest``.  As a rate, they should add up to  '
              '``100*numcpus`` on the host.',
              extra_fields={'type': ''}, cumulative=True, category='general')
define_metric(__monitor__, 'proc.stat.intr:',
              'The number of interrupts since boot.', cumulative=True, category='general')
define_metric(__monitor__, 'proc.stat.ctxt',
              'The number of context switches since boot.', cumulative=True, category='general')
define_metric(__monitor__, 'proc.stat.processes',
              'The number of processes created since boot.', cumulative=True, category='general')
define_metric(__monitor__, 'proc.stat.procs_blocked',
              'The number of processes currently blocked on I/O.', cumulative=True, category='general')
define_metric(__monitor__, 'proc.loadavg.1m',
              'The load average over 1 minute.', category='general')
define_metric(__monitor__, 'proc.loadavg.5m',
              'The load average over 5 minutes.', category='general')
define_metric(__monitor__, 'proc.loadavg.15m',
              'The load average over 15 minutes.', category='general')
define_metric(__monitor__, 'proc.loadavg.runnable',
              'The number of runnable threads/processes.', category='general')
define_metric(__monitor__, 'proc.loadavg.total_threads',
              'The total number of threads/processes.', category='general')
define_metric(__monitor__, 'proc.kernel.entropy_avail',
              'The number of bits of entropy that can be read without blocking from /dev/random', unit='bits',
              category='general')
define_metric(__monitor__, 'proc.uptime.total',
              'The total number of seconds since boot.', cumulative=True, category='general')
define_metric(__monitor__, 'proc.uptime.now',
              'The seconds since boot of idle time', unit='seconds', cumulative=True, category='general')

define_metric(__monitor__, 'proc.vmstat.pgfault',
              'The total number of minor page faults since boot.', cumulative=True, category='virtual memory')
define_metric(__monitor__, 'proc.vmstat.pgmajfault',
              'The total number of major page faults since boot', cumulative=True, category='virtual memory')
define_metric(__monitor__, 'proc.vmstat.pswpin',
              'The total number of processes swapped in since boot.', cumulative=True, category='virtual memory')
define_metric(__monitor__, 'proc.vmstat.pswpout',
              'The total number of processes swapped out since boot.', cumulative=True, category='virtual memory')
define_metric(__monitor__, 'proc.vmstat.pgppin',
              'The total number of pages swapped in since boot.', cumulative=True, category='virtual memory')
define_metric(__monitor__, 'proc.vmstat.pgpout',
              'The total number of pages swapped out in since boot.', cumulative=True, category='virtual memory')

define_metric(__monitor__, 'sys.numa.zoneallocs',
              'The number of pages allocated from the preferred node, either type=hit or type=miss.',
              extra_fields={'node': '', 'type': ''}, category='numa')
define_metric(__monitor__, 'sys.numa.foreign_allocs',
              'The number of pages allocated from node because the preferred node did not have any free.',
              extra_fields={'node': ''}, category='numa')
define_metric(__monitor__, 'sys.numa.allocation',
              'The number of pages allocated either type=locally or type=remotely for processes on this node.',
              extra_fields={'node': '', 'type': ''}, category='numa')
define_metric(__monitor__, 'sys.numa.interleave',
              'The number of pages allocated successfully by the interleave strategy.',
              extra_fields={'node': '', 'type': 'hit'}, category='numa')


define_metric(__monitor__, 'net.sockstat.num_sockets',
              'The total number of sockets allocated (only TCP).', category='sockets')
define_metric(__monitor__, 'net.sockstat.num_timewait',
              'The total number of TCP sockets currently in TIME_WAIT state.', category='sockets')
define_metric(__monitor__, 'net.sockstat.sockets_inuse',
              'The total number of sockets in use by type.',
              extra_fields={'type': ''}, category='sockets')
define_metric(__monitor__, 'net.sockstat.num_orphans',
              'The total number of orphan TCP sockets (not attached to any file descriptor).', category='sockets')
define_metric(__monitor__, 'net.sockstat.memory',
              'Memory allocated for this socket type (in bytes).',
              extra_fields={'type': ''}, unit='bytes', category='sockets')
define_metric(__monitor__, 'net.sockstat.ipfragqueues',
              'The total number of IP flows for which there are currently fragments queued for reassembly.',
              category='sockets')

define_metric(__monitor__, 'net.stat.tcp.abort',
              'The total number of connections that the kernel had to abort due broken down by reason.',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.abort.failed',
              'The total number of times the kernel failed to abort a connection because it didn\'t even have enough '
              'memory to reset it.', cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.congestion.recovery',
              'The number of times the kernel detected spurious retransmits and was able to recover part or all of the '
              'CWND, broken down by how it recovered.',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.delayedack',
              'The number of delayed ACKs sent of different types.',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.failed_accept',
              'The number of times a connection had to be dropped  after the 3WHS.  reason=full_acceptq indicates that '
              'the application isn\'t accepting connections fast enough.  You should see SYN cookies too.',
              extra_fields={'reason': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.invalid_sack',
              'The number of invalid SACKs we saw of diff types. (requires Linux v2.6.24-rc1 or newer)',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.memory.pressure',
              'The number of times a socket entered the "memory pressure" mode.', cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.memory.prune',
              'The number of times a socket had to discard received data due to low memory conditions, broken down by '
              'type.',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.packetloss.recovery',
              'The number of times we recovered from packet loss by type of recovery (e.g. fast retransmit vs SACK).',
              extra_fields={'type': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.receive.queue.full',
              'The number of times a received packet had to be dropped because the socket\'s receive queue was full '
              '(requires Linux v2.6.34-rc2 or newer)', cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.reording',
              'The number of times we detected re-ordering broken down by how.',
              extra_fields={'detectedby': ''}, cumulative=True, category='network')
define_metric(__monitor__, 'net.stat.tcp.syncookies',
              'SYN cookies (both sent & received).',
              extra_fields={'type': ''}, cumulative=True, category='network')

define_metric(__monitor__, 'iostat.disk.read_requests',
              'The total number of reads completed by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.read_merged',
              'The total number of reads merged by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.read_sectors',
              'The total number of sectors read by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.msec_read',
              'Time in msec spent reading by device',
              extra_fields={'dev': ''}, unit='milliseconds', cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.write_requests',
              'The total number of writes completed by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.write_merged',
              'The total number of writes merged by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.write_sectors',
              'The total number of sectors written by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.msec_write',
              'The total time in milliseconds spent writing by device',
              extra_fields={'dev': ''}, unit='milliseconds', cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.ios_in_progress',
              'The number of I/O operations in progress by device',
              extra_fields={'dev': ''}, cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.msec_total',
              'The total time in milliseconds doing I/O by device.',
              extra_fields={'dev': ''}, unit='milliseconds', cumulative=True, category='disk requests')
define_metric(__monitor__, 'iostat.disk.msec_weighted_total',
              'Weighted time doing I/O (multiplied by ios_in_progress) by device.',
              extra_fields={'dev': ''}, unit='milliseconds', cumulative=True, category='disk requests')

define_metric(__monitor__, 'df.1kblocks.total',
              'The total size of the file system broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, unit='bytes:1024', category='disk resources')
define_metric(__monitor__, 'df.1kblocks.used',
              'The number of blocks used broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, unit='bytes:1024', category='disk resources')
define_metric(__monitor__, 'df.1kblocks.available',
              'The number of locks available broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, unit='bytes:1024', category='disk resources')
define_metric(__monitor__, 'df.inodes.total',
              'The number of inodes broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, category='disk resources')
define_metric(__monitor__, 'df.inodes.used',
              'The number of used inodes broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, category='disk resources')
define_metric(__monitor__, 'df.inodes.free',
              'The number of free inodes broken down by mount and filesystem type.',
              extra_fields={'mount': '', 'fstype': ''}, category='disk resources')

define_metric(__monitor__, 'proc.net.bytes',
              'The total number of bytes transmitted through the interface broken down by interface and direction.',
              extra_fields={'direction': '', 'iface': ''}, unit='bytes', cumulative=True, category='network interfaces')
define_metric(__monitor__, 'proc.net.packets',
              'The total number of packets transmitted through the interface broken down by interface and direction.',
              extra_fields={'direction': '', 'iface': ''}, cumulative=True, category='network interfaces')
define_metric(__monitor__, 'proc.net.errs',
              'The total number of packet errors broken down by interface and direction.',
              extra_fields={'direction': '', 'iface': ''}, cumulative=True, category='network interfaces')
define_metric(__monitor__, 'proc.net.dropped',
              'The total number of dropped packets broken down by interface and direction.',
              extra_fields={'direction': '', 'iface': ''}, cumulative=True, category='network interfaces')

define_metric(__monitor__, 'proc.meminfo.memtotal',
              'The total number of 1 KB pages of RAM.', unit='bytes:1024', category='memory')
define_metric(__monitor__, 'proc.meminfo.memfree',
              'The total number of unused 1 KB pages of RAM. This does not include the number of cached pages which '
              'can be used when allocating memory.', unit='bytes:1024', category='memory')
define_metric(__monitor__, 'proc.meminfo.cached',
              'The total number of 1 KB pages of RAM being used to cache blocks from the filesystem.  These can be '
              'reclaimed as used to allocate memory as needed.', unit='bytes:1024', category='memory')
define_metric(__monitor__, 'proc.meminfo.buffered',
              'The total number of 1 KB pages of RAM being used in system buffers.', unit='bytes:1024',
              category='memory')

define_log_field(__monitor__, 'monitor', 'Always ``linux_system_metrics``.')
define_log_field(__monitor__, 'metric', 'The name of a metric being measured, e.g. "proc.stat.cpu".')
define_log_field(__monitor__, 'value', 'The metric value.')

define_config_option(__monitor__, 'network_interface_prefixes',
                     'The prefixes for the network interfaces to gather statistics for.  This is either a string '
                     'or a list of strings.  The prefix must be the entire string starting after ``/dev/`` and to the'
                     'regex defined by network_interface_suffix, which defaults to [0-9A-Z]+ (multiple digits or uppercase letters).  '
                     'For example, ``eth`` matches all devices starting with ``/dev/eth`` that end in a digit or an uppercase letter, '
                     'that is eth0, eth1, ethA, ethB and so on.')
define_config_option(__monitor__, 'network_interface_suffix',
                     'The suffix for network interfaces to gather statistics for.  This is a single regex that '
                     'defaults to [0-9A-Z]+ - multiple digits or uppercase letters in a row.  This is appended to each of the network_interface_prefixes '
                     'to create the full interface name when interating over network interfaces in /dev'
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

        self.options.network_interface_prefixes = self._config.get('network_interface_prefixes', default="eth")
        if isinstance(self.options.network_interface_prefixes, basestring):
            self.options.network_interface_prefixes = [self.options.network_interface_prefixes]

        self.options.network_interface_suffix = self._config.get('network_interface_suffix', default='[0-9A-Z]+')
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
        tcollector.main_loop(self.options, self.modules, None, self.tags, False, self._run_state,
                             self._sample_interval_secs)

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
        # TODO: Fix this so it works on the Windows agent.  We need to depend on the tcollectors.. but since this
        # is a Linux specific module, we don't do anything for it.
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir, 'third_party', 'tcollector',
                            'collectors')
