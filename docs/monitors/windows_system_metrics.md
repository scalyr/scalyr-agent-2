/// DECLARE path=/help/monitors/windows-system-metrics
/// DECLARE title=Windows System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

### Windows System Metrics:

A Scalyr agent monitor that records system metrics for Windows platforms.

This agent monitor plugin records CPU consumption, memory usage, and other metrics for the server on which
the agent is running.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file 
(``C:\Program Files (x86)\Scalyr\config\agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

The windows_system_metrics plugin is configured automatically by the Scalyr Agent. You do not need to include
this plugin in your configuration file.


## Viewing Data

You can see an overview of this data in the Windows System dashboard. Click the {{menuRef:Dashboards}} menu and select
{{menuRef:Windows System}}. Use the dropdown near the top of the page to select the host whose data you'd like to view.


## Log Reference

Each event recorded by this plugin will have the following fields:

|||# Field      ||| Meaning
|||# ``monitor``||| Always ``windows_system_metrics``.
|||# ``metric`` ||| The name of a metric being measured, e.g. "winsys.cpu".
|||# ``value``  ||| The metric value.

## Metrics

The tables below list all metrics recorded by the monitor.  They are broken up into different categories.

### CPU metrics
|||# Metric         ||| Fields          ||| Description
|||# ``winsys.cpu`` ||| ``type=user``   ||| The amount of time in seconds the CPU has spent executing instructions in \
                                            user space.
|||# ``winsys.cpu`` ||| ``type=system`` ||| The amount of time in seconds the CPU has spent executing instructions in \
                                            kernel space.
|||# ``winsys.cpu`` ||| ``type=idle``   ||| The amount of time in seconds the CPU has been idle.

### Uptime metrics
|||# Metric            ||| Description
|||# ``winsys.uptime`` ||| Seconds since the system boot time.

### Memory metrics
|||# Metric                      ||| Fields            ||| Description
|||# ``winsys.memory.total``     ||| ``type=swap``     ||| The number of bytes of swap space available.
|||# ``winsys.memory.used``      ||| ``type=swap``     ||| The number of bytes of swap currently in use.
|||# ``winsys.memory.free``      ||| ``type=swap``     ||| The number of bytes of swap currently free.
|||# ``winsys.memory.total``     ||| ``type=physical`` ||| The number of bytes of RAM.
|||# ``winsys.memory.used``      ||| ``type=physical`` ||| The number of bytes of RAM currently in use.
|||# ``winsys.memory.free``      ||| ``type=physical`` ||| The number of bytes of RAM that are not in use.
|||# ``winsys.memory.available`` ||| ``type=physical`` ||| The number of bytes of RAM that are available for \
                                                           allocation.  This includes memory currently in use for \
                                                           caches but can be freed for other purposes.

### Network metrics
|||# Metric                     ||| Fields             ||| Description
|||# ``winsys.network.bytes``   ||| ``direction=sent`` ||| The number of bytes transmitted by the network interfaces.
|||# ``winsys.network.bytes``   ||| ``direction=recv`` ||| The number of bytes received by the network interfaces.
|||# ``winsys.network.packets`` ||| ``direction=sent`` ||| The number of packets transmitted by the network intefaces.
|||# ``winsys.network.packets`` ||| ``direction=recv`` ||| The number of packets received by the network interfaces.

### Disk metrics
|||# Metric                        ||| Fields         ||| Description
|||# ``winsys.disk.io.bytes``      ||| ``type=read``  ||| The number of bytes read from disk.
|||# ``winsys.disk.io.bytes``      ||| ``type=write`` ||| The number of bytes written to disk.
|||# ``winsys.disk.io.ops``        ||| ``type=read``  ||| The number of disk read operations issued since boot time.
|||# ``winsys.disk.io.ops``        ||| ``type=write`` ||| The number of disk write operations issued since boot time.
|||# ``winsys.disk.usage.percent`` ||| ``partition``  ||| Disk usage percentage for each disk partition.
|||# ``winsys.disk.usage.used``    ||| ``partition``  ||| The number of bytes used for each disk partition
|||# ``winsys.disk.usage.total``   ||| ``partition``  ||| The maximum number of bytes that can be used on each disk \
                                                          partition.
|||# ``winsys.disk.usage.free``    ||| ``partition``  ||| The number of free bytes on each disk partition.

