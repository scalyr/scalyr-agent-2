/// DECLARE path=/help/monitors/linux-system-metrics
/// DECLARE title=Linux System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

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

<a name="options"></a>
## Configuration Options

| Property                     | Description | 
| ---                          | --- | 
| `network_interface_prefixes` | Optional (defaults to `eth`). A string, or a list of strings, specifying network interface prefixes. The prefix must be the full string after `/dev/`. For example, `eth` matches all devices starting with `/dev/eth`, and matches network interfaces named "eth0", "eth1", "ethA", "ethB", etc. | 
| `network_interface_suffix`   | Optional (defaults to `[0-9A-Z]+`). Suffix for the network interfaces. This is a single regular expression, appended to each of the `network_interface_prefixes`, to create the full interface name. | 
| `local_disks_only`           | Optional (defaults to `true`). Limits metric collection to locally mounted filesystems. | 
| `ignore_mounts`              | List of glob patterns for mounts to ignore. Defaults to `["/sys/*", "/dev*", "/run*", "/var/lib/docker/*", "/snap/*"]`; typically these are special docker, cgroup, and other related mount points. To include them, set an `[]` empty list. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field     | Description | 
| ---       | --- | 
| `monitor` | Always `linux_system_metrics`. | 
| `metric`  | Name of the metric, e.g. "proc.stat.cpu". Some metrics have additional fields; see the [Metrics Reference](#metrics). | 
| `value`   | Value of the metric. | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:


### General Metrics

| Metric                          | Fields | Description | 
| ---                             | ---    | --- | 
| `sys.cpu.count`                 |        | Number of CPUs on the host. | 
| `proc.stat.cpu`                 | `type` | CPU counters in units of jiffies, by `type`. Type can be `user`, `nice`, `system`, `iowait`, `irq`, `softirq`, `steal`, or `guest`. Values are cumulative since boot. You can run the command `getconf CLK_TCK` to ascertain the time span of a jiffy. Typically, the return will be `100`; the counter increments 100x a second, and one jiffy is 10 ms. As a rate, the `type` values should add up to `100*numcpus` on the host. This PowerQuery will calculate the mean rate of one-minute intervals, over a one hour time span: `metric = 'proc.stat.cpu' serverHost = 'your-server-name' value > 0 | group ct=count(), rate = (max(value) - min(value))/60 by type, timebucket('1m') | filter ct == 2 | group mean(rate) by type`. Note: we sample metrics twice a minute; filtering for `ct == 2` eliminates noise, caused by jitter. | 
| `proc.stat.intr`                |        | Number of interrupts. The value is cumulative since boot. | 
| `proc.stat.ctxt`                |        | Number of context switches. The value is cumulative since boot. | 
| `proc.stat.processes`           |        | Number of processes created. The value is cumulative since boot. | 
| `proc.stat.procs_blocked`       |        | Number of processes currently blocked on I/O. | 
| `proc.loadavg.1min`             |        | Load average over 1 minute. | 
| `proc.loadavg.5min`             |        | Load average over 5 minutes. | 
| `proc.loadavg.15min`            |        | Load average over 15 minutes. | 
| `proc.loadavg.runnable`         |        | Number of runnable threads/processes. | 
| `proc.loadavg.total_threads`    |        | Number of threads/processes. | 
| `proc.kernel.entropy_avail`     |        | Bits of entropy that can be read without blocking from `/dev/random`. | 
| `proc.uptime.total`             |        | Seconds since boot. | 
| `proc.uptime.now`               |        | Seconds of idle time. The value is cumulative since boot. | 

### Virtual Memory Metrics

| Metric                      | Description | 
| ---                         | --- | 
| `proc.vmstat.pgfault`       | Number of minor page faults. The value is cumulative since boot. | 
| `proc.vmstat.pgmajfault`    | Number of major page faults. The value is cumulative since boot. | 
| `proc.vmstat.pswpin`        | Number of processes swapped in. The value is cumulative since boot. | 
| `proc.vmstat.pswpout`       | Number of processes swapped out. The value is cumulative since boot. | 
| `proc.vmstat.pgpgin`        | Number of pages swapped in. The value is cumulative since boot. | 
| `proc.vmstat.pgpgout`       | Number of pages swapped out. The value is cumulative since boot. | 

### NUMA Metrics

| Metric                       | Fields     | Description | 
| ---                          | ---        | --- | 
| `sys.numa.zoneallocs`        | `node`, \
                                   `type`     | Number of pages allocated on the node, by `node` and `type`. The value is cumulative since boot. Type is either `hit` (memory was successfully allocated on the intended node); or `miss` (memory was allocated on the node, despite the preference for a different node). | 
| `sys.numa.foreign_allocs`    | `node`     | Number of pages allocated on the node because the preferred node had none free, by `node`. The value is cumulative since boot. Each increment also has a `type='miss'` increment for a different node in `sys.numa.zoneallocs`. | 
| `sys.numa.allocation`        | `node`, \
                                   `type`     | Number of pages allocated, by `node` and `type`. The value is cumulative since boot. Type is either 'locally', or 'remotely', for processes on this node. | 
| `sys.numa.interleave`        | `node`, \
                                   `type=hit` | Number of pages successfully allocated by the interleave strategy. The value is cumulative since boot. | 

### Sockets Metrics

| Metric                          | Fields | Description | 
| ---                             | ---    | --- | 
| `net.sockstat.num_sockets`      |        | Number of sockets allocated (only TCP). | 
| `net.sockstat.num_timewait`     |        | Number of TCP sockets currently in TIME_WAIT state. | 
| `net.sockstat.sockets_inuse`    | `type` | Number of sockets in use, by `type` (e.g. `tcp`, `udp`, `raw`, etc.). | 
| `net.sockstat.num_orphans`      |        | Number of orphan TCP sockets (not attached to any file descriptor). | 
| `net.sockstat.memory`           | `type` | Bytes allocated, by socket `type`. | 
| `net.sockstat.ipfragqueues`     |        | Number of IP flows for which there are currently fragments queued for reassembly. | 

### Network Metrics

| Metric                                | Fields       | Description | 
| ---                                   | ---          | --- | 
| `net.stat.tcp.abort`                  | `type`       | Number of connections aborted by the kernel, by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L191) for `type` definitions. `type='out_of_memory'` is especially bad; the kernel dropped a connection due to too many orphaned sockets. Other types are normal (e.g. `type='timeout'`). | 
| `net.stat.tcp.abort.failed`           |              | Number of times the kernel failed to abort a connection because it did not have enough memory to reset it. The value is cumulative since boot. | 
| `net.stat.tcp.congestion.recovery`    | `type`       | Number of times the kernel detected spurious retransmits, and recovered all or part of the CWND, by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L179) for `type` definitions. | 
| `net.stat.tcp.delayedack`             | `type`       | Number of delayed ACKs sent, by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L141) for `type` definitions. | 
| `net.stat.tcp.failed_accept`          | `reason`     | Number of connections dropped after the 3WHS, by `reason`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L150) for `reason` definitions. A reason of `full_acceptq` indicates the application is not accepting connections fast enough; also check your SYN cookies. | 
| `net.stat.tcp.invalid_sack`           | `type`       | Number of invalid SACKs, by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L215) for `type` definitions. (This metric requires Linux v2.6.24-rc1 or newer.) | 
| `net.stat.tcp.memory.pressure`        |              | Number of times a socket entered the "memory pressure" mode. The value is cumulative since boot. | 
| `net.stat.tcp.memory.prune`           | `type`       | Number of times a socket discarded received data, due to low memory conditions, by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L134) for `type` definitions. | 
| `net.stat.tcp.packetloss.recovery`    | `type`       | Number of recoveries from packet loss, by `type` of recovery. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L134) for `type` definitions. | 
| `net.stat.tcp.receive.queue.full`     |              | Number of times a received packet was dropped because the socket's receive queue was full. The value is cumulative since boot. (This metric requires Linux v2.6.34-rc2 or newer.) | 
| `net.stat.tcp.reording`               | `detectedby` | Number of times we detected re-ordering, by `detectedby`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L169) for `detectedby` definitions. | 
| `net.stat.tcp.syncookies`             | `type`       | Number of SYN cookies (both sent & received), by `type`. The value is cumulative since boot. See the [tcollector documentation](https://github.com/OpenTSDB/tcollector/blob/37ae920d83c1002da66b5201a5311b1714cb5c14/collectors/0/netstat.py#L126) for `type` definitions. | 

### Disk Requests Metrics

| Metric                               | Fields | Description | 
| ---                                  | ---    | --- | 
| `iostat.disk.read_requests`          | `dev`  | Number of reads completed, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.read_merged`            | `dev`  | Number of reads merged, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.read_sectors`           | `dev`  | Number of sectors read, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.msec_read`              | `dev`  | Milliseconds spent reading, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.write_requests`         | `dev`  | Number of completed writes, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.write_merged`           | `dev`  | Number of writes merged, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.write_sectors`          | `dev`  | Number of sectors written, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.msec_write`             | `dev`  | Milliseconds spent writing, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.ios_in_progress`        | `dev`  | Number of I/O operations in progress, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.msec_total`             | `dev`  | Milliseconds performing I/O, by device (`dev`). The value is cumulative since boot. | 
| `iostat.disk.msec_weighted_total`    | `dev`  | Weighted total: milliseconds performing I/O multiplied by `ios_in_progress`, by device (`dev`). The value is cumulative since boot. | 

### Disk Resources Metrics

| Metric                 | Fields   | Description | 
| ---                    | ---      | --- | 
| `df.1kblocks.total`    | `mount`, \
                             `fstype` | Size of the file system in 1 kB blocks, by mount and filesystem type. | 
| `df.1kblocks.used`     | `mount`, \
                             `fstype` | Number of 1 kB blocks used, by mount and filesystem type. | 
| `df.1kblocks.free`     | `mount`, \
                             `fstype` | Number of 1 kB blocks free, by mount and filesystem type. | 
| `df.inodes.total`      | `mount`, \
                             `fstype` | Number of inodes, by mount and filesystem type. | 
| `df.inodes.used`       | `mount`, \
                             `fstype` | Number of used inodes, by mount and filesystem type. | 
| `df.inodes.free`       | `mount`, \
                             `fstype` | Number of free inodes, by mount and filesystem type. | 

### Memory Metrics

| Metric                     | Description | 
| ---                        | --- | 
| `proc.meminfo.memtotal`    | Number of 1 kB pages of RAM. | 
| `proc.meminfo.memfree`     | Number of unused 1 kB pages of RAM. This does not include cached pages, which can be used to allocate memory as needed. | 
| `proc.meminfo.cached`      | Number of 1 kB pages of RAM used to cache blocks from the filesystem. These can be used to allocate memory as needed. | 
| `proc.meminfo.buffers`     | Number of 1 KB pages of RAM being used in system buffers. | 
