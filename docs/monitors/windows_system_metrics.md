/// DECLARE path=/help/monitors/windows-system-metrics
/// DECLARE title=Windows System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

# Windows System Metrics

Import CPU consumption, memory usage, and other metrics for a Windows server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can disable collection of these metrics by setting `implicit_metric_monitor: false` at the top level of the Agent [configuration file](/help/scalyr-agent#plugins).


## Installation


1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Windows server.

This plugin is automatically configured. On some Windows installations, you must run [diskperf -y](https://docs.microsoft.com/en-us/windows-server/administration/windows-commands/diskperf) as an Administrator to enable disk io metrics.


2\. Confirm

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > system. You will see an overview of Windows system metrics, across all Windows servers running this plugin. The dashboard only shows some of the data collected. Go to Search view and query [monitor = 'windows_system_metrics'](/events?filter=monitor+%3D+%27windows_system_metrics%27) to view all data.

For help, contact Support.


<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Meaning |
|---|---|
| `monitor`| Always `windows_system_metrics`. |
| `metric` | Name of the metric, e.g. "winsys.cpu". Some metrics have additional fields; see the [Metrics Reference](#metrics). |
| `value`  | Value of the metric. |


&nbsp;


<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:

### CPU Metrics

| Metric         | Fields          | Description |
|---|---|---|
| `winsys.cpu` | `type=user`   | Seconds of user space CPU execution. The value is cumulative since boot. |
| `winsys.cpu` | `type=system` | Seconds of kernel space CPU execution. The value is cumulative since boot. |
| `winsys.cpu` | `type=idle`   | Seconds of idle CPU. The value is cumulative since boot. |

&nbsp;

### Uptime Metrics

| Metric            | Description |
|---|---|
| `winsys.uptime` | Seconds since system boot. |

&nbsp;

### Memory Metrics

| Metric                      | Fields            | Description |
|---|---|---|
| `winsys.memory.total`     | `type=swap`     | Total bytes of swap memory. |
| `winsys.memory.used`      | `type=swap`     | Bytes of used swap memory. |
| `winsys.memory.free`      | `type=swap`     | Bytes of free swap memory. |
| `winsys.memory.total`     | `type=physical` | Total bytes of RAM. |
| `winsys.memory.used`      | `type=physical` | Bytes of used RAM. |
| `winsys.memory.free`      | `type=physical` | Bytes of free RAM. |
| `winsys.memory.available` | `type=physical` | Bytes of available RAM. This includes memory used for caches that can be freed for other purposes. |

&nbsp;

### Network Metrics

| Metric                     | Fields             | Description |
|---|---|---|

| `winsys.network.bytes`   | `direction=sent` | Bytes transmitted by the network interfaces. The value is cumulative since boot. |
| `winsys.network.bytes`   | `direction=recv` | Bytes received by the network interfaces. The value is cumulative since boot. |
| `winsys.network.packets` | `direction=sent` | Number of packets transmitted by the network interfaces. The value is cumulative since boot. |
| `winsys.network.packets` | `direction=recv` | Number of packets received by the network interfaces. The value is cumulative since boot. |

&nbsp;

### Disk Metrics

| Metric                        | Fields         | Description |
|---|---|---|
| `winsys.disk.io.bytes`      | `type=read`  | Bytes read from disk. The value is cumulative since boot. |
| `winsys.disk.io.bytes`      | `type=write` | Bytes written to disk. The value is cumulative since boot. |
| `winsys.disk.io.ops`        | `type=read`  | Number of disk read operations. The value is cumulative since boot. |
| `winsys.disk.io.ops`        | `type=write` | Number of disk write operations. The value is cumulative since boot. |
| `winsys.disk.usage.percent` | `partition`  | Percentage of disk used, by partition. |
| `winsys.disk.usage.used`    | `partition`  | Bytes of disk used, by partition. |
| `winsys.disk.usage.total`   | `partition`  | Maximum usable bytes of disk, by partition. |
| `winsys.disk.usage.free`    | `partition`  | Bytes of disk free, by partition. |


<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
