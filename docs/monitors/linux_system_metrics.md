/// DECLARE path=/help/monitors/linux-system-metrics
/// DECLARE title=Linux System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Linux System Metrics

This agent monitor plugin records CPU consumption, memory usage, and other metrics for the server on which
the agent is running.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

The linux_system_metrics plugin is configured automatically by the Scalyr Agent. You do not need to include
this plugin in your configuration file.

## Viewing Data

You can see an overview of this data in the System dashboard. Click the {{menuRef:Dashboards}} menu and select
{{menuRef:System}}. Use the dropdown near the top of the page to select the host whose data you'd like to view.

## Configuration Reference

|||# Option                        ||| Usage
|||# ``network_interface_prefixes``||| The prefixes for the network interfaces to gather statistics for.  This is \
                                       either a string or a list of strings.  The prefix must be the entire string \
                                       starting after ``/dev/`` and to theregex defined by network_interface_suffix, \
                                       which defaults to [0-9A-Z]+ (multiple digits or uppercase letters).  For \
                                       example, ``eth`` matches all devices starting with ``/dev/eth`` that end in a \
                                       digit or an uppercase letter, that is eth0, eth1, ethA, ethB and so on.
|||# ``network_interface_suffix``  ||| The suffix for network interfaces to gather statistics for.  This is a single \
                                       regex that defaults to [0-9A-Z]+ - multiple digits or uppercase letters in a \
                                       row.  This is appended to each of the network_interface_prefixes to create the \
                                       full interface name when interating over network interfaces in /dev
|||# ``local_disks_only``          ||| (defaults to true) Limits the metrics to only locally mounted filesystems

## Log reference

Each event recorded by this plugin will have the following fields:

|||# Field      ||| Meaning
|||# ``monitor``||| Always ``linux_system_metrics``.
|||# ``metric`` ||| The name of a metric being measured, e.g. "proc.stat.cpu".
|||# ``value``  ||| The metric value.

## Metrics

The table below describes the metrics recorded by the monitor.


### general metrics

|||# Metric                         ||| Fields   ||| Description
|||# ``sys.cpu.count``              |||          ||| The number of CPUs on the system
|||# ``proc.stat.cpu``              ||| ``type`` ||| CPU counters in units of jiffies, where ``type`` can be one of \
                                                     ``user``, ``nice``, ``system``,  ``iowait``, ``irq``, ``softirq``, \
                                                     ``steal``, ``guest``.  As a rate, they should add up to  \
                                                     ``100*numcpus`` on the host.
|||# ``proc.stat.intr``             |||          ||| The number of interrupts since boot.
|||# ``proc.stat.ctxt``             |||          ||| The number of context switches since boot.
|||# ``proc.stat.processes``        |||          ||| The number of processes created since boot.
|||# ``proc.stat.procs_blocked``    |||          ||| The number of processes currently blocked on I/O.
|||# ``proc.loadavg.1min``          |||          ||| The load average over 1 minute.
|||# ``proc.loadavg.5min``          |||          ||| The load average over 5 minutes.
|||# ``proc.loadavg.15min``         |||          ||| The load average over 15 minutes.
|||# ``proc.loadavg.runnable``      |||          ||| The number of runnable threads/processes.
|||# ``proc.loadavg.total_threads`` |||          ||| The total number of threads/processes.
|||# ``proc.kernel.entropy_avail``  |||          ||| The number of bits of entropy that can be read without blocking from \
                                                     /dev/random
|||# ``proc.uptime.total``          |||          ||| The total number of seconds since boot.
|||# ``proc.uptime.now``            |||          ||| The seconds since boot of idle time

### virtual memory metrics

|||# Metric                     ||| Description
|||# ``proc.vmstat.pgfault``    ||| The total number of minor page faults since boot.
|||# ``proc.vmstat.pgmajfault`` ||| The total number of major page faults since boot
|||# ``proc.vmstat.pswpin``     ||| The total number of processes swapped in since boot.
|||# ``proc.vmstat.pswpout``    ||| The total number of processes swapped out since boot.
|||# ``proc.vmstat.pgpgin``     ||| The total number of pages swapped in since boot.
|||# ``proc.vmstat.pgpgout``    ||| The total number of pages swapped out in since boot.

### numa metrics

|||# Metric                      ||| Fields       ||| Description
|||# ``sys.numa.zoneallocs``     ||| ``node``, \
                                     ``type``     ||| The number of pages allocated from the preferred node, either \
                                                      type=hit or type=miss.
|||# ``sys.numa.foreign_allocs`` ||| ``node``     ||| The number of pages allocated from node because the preferred node \
                                                      did not have any free.
|||# ``sys.numa.allocation``     ||| ``node``, \
                                     ``type``     ||| The number of pages allocated either type=locally or type=remotely \
                                                      for processes on this node.
|||# ``sys.numa.interleave``     ||| ``node``, \
                                     ``type=hit`` ||| The number of pages allocated successfully by the interleave \
                                                      strategy.

### sockets metrics

|||# Metric                         ||| Fields   ||| Description
|||# ``net.sockstat.num_sockets``   |||          ||| The total number of sockets allocated (only TCP).
|||# ``net.sockstat.num_timewait``  |||          ||| The total number of TCP sockets currently in TIME_WAIT state.
|||# ``net.sockstat.sockets_inuse`` ||| ``type`` ||| The total number of sockets in use by type.
|||# ``net.sockstat.num_orphans``   |||          ||| The total number of orphan TCP sockets (not attached to any file \
                                                     descriptor).
|||# ``net.sockstat.memory``        ||| ``type`` ||| Memory allocated for this socket type (in bytes).
|||# ``net.sockstat.ipfragqueues``  |||          ||| The total number of IP flows for which there are currently fragments \
                                                     queued for reassembly.

### network metrics

|||# Metric                               ||| Fields         ||| Description
|||# ``net.stat.tcp.abort``               ||| ``type``       ||| The total number of connections that the kernel had to \
                                                                 abort due broken down by reason.
|||# ``net.stat.tcp.abort.failed``        |||                ||| The total number of times the kernel failed to abort a \
                                                                 connection because it didn't even have enough memory to \
                                                                 reset it.
|||# ``net.stat.tcp.congestion.recovery`` ||| ``type``       ||| The number of times the kernel detected spurious \
                                                                 retransmits and was able to recover part or all of the \
                                                                 CWND, broken down by how it recovered.
|||# ``net.stat.tcp.delayedack``          ||| ``type``       ||| The number of delayed ACKs sent of different types.
|||# ``net.stat.tcp.failed_accept``       ||| ``reason``     ||| The number of times a connection had to be dropped  after \
                                                                 the 3WHS.  reason=full_acceptq indicates that the \
                                                                 application isn't accepting connections fast enough.  You \
                                                                 should see SYN cookies too.
|||# ``net.stat.tcp.invalid_sack``        ||| ``type``       ||| The number of invalid SACKs we saw of diff types. \
                                                                 (requires Linux v2.6.24-rc1 or newer)
|||# ``net.stat.tcp.memory.pressure``     |||                ||| The number of times a socket entered the "memory \
                                                                 pressure" mode.
|||# ``net.stat.tcp.memory.prune``        ||| ``type``       ||| The number of times a socket had to discard received data \
                                                                 due to low memory conditions, broken down by type.
|||# ``net.stat.tcp.packetloss.recovery`` ||| ``type``       ||| The number of times we recovered from packet loss by type \
                                                                 of recovery (e.g. fast retransmit vs SACK).
|||# ``net.stat.tcp.receive.queue.full``  |||                ||| The number of times a received packet had to be dropped \
                                                                 because the socket's receive queue was full (requires \
                                                                 Linux v2.6.34-rc2 or newer)
|||# ``net.stat.tcp.reording``            ||| ``detectedby`` ||| The number of times we detected re-ordering broken down \
                                                                 by how.
|||# ``net.stat.tcp.syncookies``          ||| ``type``       ||| SYN cookies (both sent & received).

### disk requests metrics

|||# Metric                              ||| Fields  ||| Description
|||# ``iostat.disk.read_requests``       ||| ``dev`` ||| The total number of reads completed by device
|||# ``iostat.disk.read_merged``         ||| ``dev`` ||| The total number of reads merged by device
|||# ``iostat.disk.read_sectors``        ||| ``dev`` ||| The total number of sectors read by device
|||# ``iostat.disk.msec_read``           ||| ``dev`` ||| Time in msec spent reading by device
|||# ``iostat.disk.write_requests``      ||| ``dev`` ||| The total number of writes completed by device
|||# ``iostat.disk.write_merged``        ||| ``dev`` ||| The total number of writes merged by device
|||# ``iostat.disk.write_sectors``       ||| ``dev`` ||| The total number of sectors written by device
|||# ``iostat.disk.msec_write``          ||| ``dev`` ||| The total time in milliseconds spent writing by device
|||# ``iostat.disk.ios_in_progress``     ||| ``dev`` ||| The number of I/O operations in progress by device
|||# ``iostat.disk.msec_total``          ||| ``dev`` ||| The total time in milliseconds doing I/O by device.
|||# ``iostat.disk.msec_weighted_total`` ||| ``dev`` ||| Weighted time doing I/O (multiplied by ios_in_progress) by \
                                                         device.

### disk resources metrics

|||# Metric                ||| Fields     ||| Description
|||# ``df.1kblocks.total`` ||| ``mount``, \
                               ``fstype`` ||| The total size of the file system broken down by mount and filesystem type.
|||# ``df.1kblocks.used``  ||| ``mount``, \
                               ``fstype`` ||| The number of blocks used broken down by mount and filesystem type.
|||# ``df.inodes.total``   ||| ``mount``, \
                               ``fstype`` ||| The number of inodes broken down by mount and filesystem type.
|||# ``df.inodes.used``    ||| ``mount``, \
                               ``fstype`` ||| The number of used inodes broken down by mount and filesystem type.
|||# ``df.inodes.free``    ||| ``mount``, \
                               ``fstype`` ||| The number of free inodes broken down by mount and filesystem type.

### memory metrics

|||# Metric                    ||| Description
|||# ``proc.meminfo.memtotal`` ||| The total number of 1 KB pages of RAM.
|||# ``proc.meminfo.memfree``  ||| The total number of unused 1 KB pages of RAM. This does not include the number of \
                                   cached pages which can be used when allocating memory.
|||# ``proc.meminfo.cached``   ||| The total number of 1 KB pages of RAM being used to cache blocks from the filesystem.  \
                                   These can be reclaimed as used to allocate memory as needed.
|||# ``proc.meminfo.buffers``  ||| The total number of 1 KB pages of RAM being used in system buffers.
