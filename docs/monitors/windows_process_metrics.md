/// DECLARE path=/help/monitors/windows-process-metrics
/// DECLARE title=Windows Process Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

# Windows Process Metrics

Import CPU consumption, memory usage, and other metrics for a process, or group of processes, on a Windows server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can use this plugin to monitor resource usage for a web server, database, or other application. 32-bit Windows systems are not supported.

This plugin requires installation of the python module `psutil`, typically with the command `pip install psutil`.

You can disable collection of these metrics by setting `implicit_agent_process_metrics_monitor: false` at the top level of the Agent [configuration file](/help/scalyr-agent#plugins).


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Windows server.


2\. Configure the Scalyr Agent to import process metrics

Open the Scalyr Agent configuration file, located at `C:\Program Files (x86)\Scalyr\config\agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for windows process metrics:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.windows_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
      }
    ]

The `id` property lets you identify the command whose output you are importing. It shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin, to import metrics from multiple processes. Add a separate `{...}` stanza for each instance, and set unique `id`s.

The `commandline` property is a [regular expression](https://app.scalyr.com/help/regex), matching on the command line output of `tasklist`, or `wmic process list`. If multiple processes match, only the first is used. The above example imports metrics for the first process whose command line output matches the regular expression `java.*tomcat6`.

You can also select a process by process identifier (PID). See [Configuration Options](#options) below.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for data to send.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


4.\ Configure the process metrics dashboard for each `id`

Log into Scalyr and click Dashboards > Windows Process Metrics. At the top of the dashboard you can select the `serverHost` and `process` of interest. (We map the `instance` field, explained above, to `process`).

Click `...` in upper right of the page and select "Edit JSON". Find these lines near the top of the JSON file:

    // On the next line, list each "id" that you've used in a windows_process_metrics
    // clause in the Scalyr Agent configuration file (agent.json).
    values: [ "agent" ]

The "agent" id is used to report metrics for the Scalyr Agent.

Add each `id` you created to the `values` list. For example, to add "tomcat":

    values: [ "agent", "tomcat" ]

Save the file. To view all data collected by this plugin, across all servers, go to Search view and query [monitor = 'windows_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27windows_process_metrics%27).

For help, contact Support.

<a name="options"></a>
## Configuration Options


| Option         | Usage |
|---|---|
| `module`     | Always `scalyr_agent.builtin_monitors.windows_process_metrics`. |
| `id`         | An id, included with each event. Shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin to import metrics from multiple processes. Each instance has a separate `{...}` stanza in the configuration file (`C:\Program Files (x86)\Scalyr\config\agent.json`). |
| `commandline`| A regular expression, matching on the command line output of `tasklist`, or `wmic process list`. Selects the process of interest. If multiple processes match, only metrics from the first match are imported. |
| `pid`        | Process identifier (PID). An alternative to `commandline` to select a process. If `commandline` is set, this property is ignored. |


&nbsp;

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field       | Meaning |
|---|---|
| `monitor` | Always `windows_process_metrics`. |
| `instance`| The `id` value from Step **2**, e.g. `tomcat`. |
| `app`     | Same as `instance`; created for compatibility with the original Scalyr Agent. |
| `metric`  | Name of the metric, e.g. "winproc.cpu". Some metrics have additional fields; see the [Metrics Reference](#metrics). |
| `value`   | Value of the metric. |

&nbsp;

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:

### CPU Metrics

| Metric          | Fields          | Description |
|---|---|---|
| `winproc.cpu` | `type=user`   | Seconds of user space CPU execution. The value is cumulative since process start; see `winproc.uptime`. |
| `winproc.cpu` | `type=system` | Seconds of kernel space CPU execution. The value is cumulative since process start; see `winproc.uptime`. |

&nbsp;

### General Metrics

| Metric              | Description |
|---|---|
| `winproc.uptime`  | Process uptime, in seconds. |
| `winproc.threads` | Number of threads used by the process. |

&nbsp;

### Memory Metrics

| Metric                | Fields                      | Description |
|---|---|---|
| `winproc.mem.bytes` | `type=working_set`        | Bytes of physical memory used by the process's working set. Memory that must be paged in for the process to execute. |
| `winproc.mem.bytes` | `type=peak_working_set`   | Peak working set size, in bytes, for the process since creation. |
| `winproc.mem.bytes` | `type=paged_pool`         | Paged-pool usage, in bytes. Swappable memory in use. |
| `winproc.mem.bytes` | `type=peak_paged_pool`    | Peak paged-pool usage, in bytes. |
| `winproc.mem.bytes` | `type=nonpaged_pool`      | Nonpaged pool usage, in bytes. Memory in use that cannot be swapped out to disk. |
| `winproc.mem.bytes` | `type=peak_nonpaged_pool` | Peak nonpaged pool usage, in bytes. |
| `winproc.mem.bytes` | `type=pagefile`           | Pagefile usage, in bytes. Bytes the system has committed for this running process. |
| `winproc.mem.bytes` | `type=peak_pagefile`      | Peak pagefile usage, in bytes. |
| `winproc.mem.bytes` | `type=rss`                | Current resident memory size, in bytes. This should be the same as the working set. |
| `winproc.mem.bytes` | `type=vms`                | Virtual memory size, in bytes. Does not include shared pages. |

&nbsp;

### Disk Metrics

| Metric                 | Fields         | Description |
|---|---|---|
| `winproc.disk.ops`   | `type=read`  | Number of disk read requests. The value is cumulative since process start; see `winproc.uptime`. |
| `winproc.disk.ops`   | `type=write` | Number of disk write requests. The value is cumulative since process start; see `winproc.uptime`. |
| `winproc.disk.bytes` | `type=read`  | Bytes read from disk. The value is cumulative since process start; see `winproc.uptime`. |
| `winproc.disk.bytes` | `type=write` | Bytes written to disk. The value is cumulative since process start; see `winproc.uptime`. |

&nbsp;

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
