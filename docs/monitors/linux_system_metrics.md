/// DECLARE path=/help/monitors/linux-system-metrics
/// DECLARE title=Linux System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

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


## Log Reference

Each event recorded by this plugin will have the following fields:

|||# Field                    ||| Meaning
|||# ``monitor``              ||| Always ``linux_system_metrics``
|||# ``metric``               ||| The name of a metric being measured, e.g. "proc.stat.cpu"
|||# ``value``                ||| The metric value

Some metrics have additional fields, as documented below.

Here is a list of the metrics most commonly used in dashboards and alerts recorded by this plugin.
For a complete list, please see refer to list in the comments at the top of the
[source file](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/builtin_monitors/linux_system_metrics.py).

|||# Metric                             ||| Fields    ||| Description
||| ``proc.stat.cpu``                   ||| ``type``  ||| CPU counters in units of jiffers, where ``type`` can be one \
                                                          of ``user``, ``nice``, ``system``,  ``iowait``, ``irq``, \
                                                          ``softirq``, ``steal``, ``guest``.  As a rate, they should \
                                                           add up to  ``100*numcpus`` on the host.                             
||| ``proc.loadavg.1m``                 |||           ||| The load average over 1 minute.
||| ``proc.loadavg.5m``                 |||           ||| The load average over 5 minutes.
||| ``proc.loadavg.15m``                |||           ||| The load average over 15 minutes.
||| ``proc.uptime.total``               |||           ||| The total number of seconds since boot.
||| ``proc.meminfo.memtotal``           |||           ||| The total number of 1 KB pages of RAM. 
||| ``proc.meminfo.memfree``            |||           ||| The total number of unused 1 KB pages of RAM. This does not \
                                                          include the number of cached pages which can be used when \
                                                          allocating memory.
||| ``proc.meminfo.cached``             |||           ||| The total number of 1 KB pages of RAM being used to cache \
                                                          blocks from the filesystem.  These can be reclaimed as used \
                                                          to allocate memory as needed. 
||| ``proc.meminfo.buffered``           |||           ||| The total number of 1 KB pages of RAM being used in system \
                                                          buffers.
||| ``proc.vmstat.pgfault``             |||           ||| The total number of minor page faults since boot.
||| ``proc.vmstat.pgmajfault``          |||           ||| The total number of major page faults since boot.
||| ``net.sockstat.num_sockets``        |||           ||| The total number of sockets allocated (only TCP) since boot.
|||  ``net.sockstat.num_timewait``      |||           ||| The total number of TCP sockets currently in TIME_WAIT state.
|||  ``net.sockstat.sockets_inuse``     ||| ``type``  ||| The total number of sockets in use by socket type.
||| ``net.stat.tcp.abort``              ||| ``type``  ||| The total number of connections that the kernel had to abort\
                                                          broken down by reason.
||| ``iostat.disk.read_requests``       ||| ``dev``   ||| The total number of reads completed by device.
||| ``iostat.disk.msec_read``           ||| ``dev``   ||| The total time in milliseconds spent reading by device.
||| ``iostat.disk.write_requests``      ||| ``dev``   ||| The total number of writes completed by device.
||| ``iostat.disk.msec_write``          ||| ``dev``   ||| The total time in milliseconds spent writing by device.
||| ``iostat.disk.ios_in_progress``     ||| ``dev``   ||| The total number of I/O operations in progress by device.
||| ``iostat.disk.msec_total``          ||| ``dev``   ||| The total time in milliseconds doing I/O by device.
||| ``iostat.disk.msec_weighted_total`` ||| ``dev``   ||| Weighted time doing I/O (multiplied by ios_in_progress) by \
                                                          device.
||| ``df.1kblocks.total``               ||| ``mount``, \
                                            ``fstype``||| The total size of the file system broken down by mount and \
                                                          filesystem type, in units of 1KB blocks.
||| ``df.1kblocks.used``                ||| ``mount``, \
                                            ``fstype``||| The total number of used 1KB blocks on the file system broken\
                                                          down by mount and filesystem type.
||| ``df.1kblocks.available``           ||| ``mount``, \
                                            ``fstype``||| The total number of availabled 1KB blocks on the file system \
                                                          broken down by mount and filesystem type.
||| ``proc.net.bytes``                  ||| ``iface``, \
                                            ``direction`` ||| The total number of bytes transmitted through the interface \
                                                              broken down by interface and direction.
||| ``proc.net.packets``                ||| ``iface``, \
                                            ``direction`` ||| The total number of packets transmitted through the interface \
                                                              broken down by interface and direction.
||| ``proc.net.errs``                   ||| ``iface``, \
                                            ``direction`` ||| The total number of packet errors broken down by \
                                                              interface and direction.
||| ``proc.net.dropped``                ||| ``iface``, \
                                            ``direction`` ||| The total number of dropped packet broken down by \
                                                              interface and direction.


|||# Metric name *(additional fields)*        ||| Description
|||# ``proc.stat.cpu *(type)*``  ||| CPU counters in units of jiffers, where ``type`` can be one \
                                                          of ``user``, ``nice``, ``system``,  ``iowait``, ``irq``, \
                                                          ``softirq``, ``steal``, ``guest``.  As a rate, they should \
                                                           add up to  ``100*numcpus`` on the host.                             
|||# ``proc.loadavg.1m``  ||| The load average over 1 minute.
|||# ``proc.loadavg.5m``  ||| The load average over 5 minutes.
|||# ``proc.loadavg.15m``  ||| The load average over 15 minutes.
|||# ``proc.uptime.total``  ||| The total number of seconds since boot.
|||# ``proc.meminfo.memtotal``  ||| The total number of 1 KB pages of RAM. 
|||# ``proc.meminfo.memfree``  ||| The total number of unused 1 KB pages of RAM. This does not \
                                                          include the number of cached pages which can be used when \
                                                          allocating memory.
|||# ``proc.meminfo.cached``  ||| The total number of 1 KB pages of RAM being used to cache \
                                                          blocks from the filesystem.  These can be reclaimed as used \
                                                          to allocate memory as needed. 
|||# ``proc.meminfo.buffered``     ||| The total number of 1 KB pages of RAM being used in system \
                                                          buffers.
|||# ``proc.vmstat.pgfault``       ||| The total number of minor page faults since boot.
|||# ``proc.vmstat.pgmajfault``      ||| The total number of major page faults since boot.
|||# ``net.sockstat.num_sockets``   ||| The total number of sockets allocated (only TCP) since boot.
|||#  ``net.sockstat.num_timewait``      ||| The total number of TCP sockets currently in TIME_WAIT state.
|||#  ``net.sockstat.sockets_inuse *(type)*``  ||| The total number of sockets in use by socket type.
|||# ``net.stat.tcp.abort *(type)*``  ||| The total number of connections that the kernel had to abort\
                                                          broken down by reason.
|||# ``iostat.disk.read_requests *(dev)*``   ||| The total number of reads completed by device.
|||# ``iostat.disk.msec_read *(dev)*``   ||| The total time in milliseconds spent reading by device.
|||# ``iostat.disk.write_requests *(dev)*``   ||| The total number of writes completed by device.
|||# ``iostat.disk.msec_write *(dev)*``   ||| The total time in milliseconds spent writing by device.
|||# ``iostat.disk.ios_in_progress *(dev)*``   ||| The total number of I/O operations in progress by device.
|||# ``iostat.disk.msec_total *(dev)*``   ||| The total time in milliseconds doing I/O by device.
|||# ``iostat.disk.msec_weighted_total *(dev)*``   ||| Weighted time doing I/O (multiplied by ios_in_progress) by \
                                                          device.
|||# ``df.1kblocks.total *(mount,fstype)*``||| The total size of the file system broken down by mount and \
                                                          filesystem type, in units of 1KB blocks.
|||# ``df.1kblocks.used *(mount,fstype)*``||| The total number of used 1KB blocks on the file system broken\
                                                          down by mount and filesystem type.
|||# ``df.1kblocks.available *(mount,fstype)*``||| The total number of availabled 1KB blocks on the file system \
                                                          broken down by mount and filesystem type.
|||# ``proc.net.bytes *(iface,direction)*`` ||| The total number of bytes transmitted through the interface \
                                                              broken down by interface and direction.
|||# ``proc.net.packets *(iface,direction)*`` ||| The total number of packets transmitted through the interface \
                                                              broken down by interface and direction.
|||# ``proc.net.errs *(iface,direction)*`` ||| The total number of packet errors broken down by \
                                                              interface and direction.
|||# ``proc.net.dropped *(iface,direction)*`` ||| The total number of dropped packet broken down by \
                                                              interface and direction.

