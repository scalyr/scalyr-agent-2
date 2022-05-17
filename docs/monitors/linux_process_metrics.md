/// DECLARE path=/help/monitors/linux-process-metrics;/appDashboard
/// DECLARE title=Linux Process Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Linux Process Metrics

Import CPU consumption, memory usage, and other metrics for a process, or group of processes, on a Linux server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can use this plugin to monitor resource usage for a web server, database, or other application.


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Linux server.


2\. Configure the Scalyr Agent to import process metrics

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for linux process metrics:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
      }
    ]

The `id` property lets you identify the process you are monitoring. It is included in each event as a field named `instance`. The `commandline` property is a [regular expression](https://app.scalyr.com/help/regex), matching on the command line output of `ps aux`. If multiple processes match, only the first is used by default. The above example imports metrics for the first process whose command line output matches the regular expression `java.*tomcat6`.

To group *all* processes that match `commandline`, add the property `aggregate_multiple_processes`, and set it to `true`. Each metric will be a summation for all matched processes. For example, the `app.cpu` metric will sum CPU used for all matched processes. To match all processes whose command line output matches the regular expression `java.*tomcat6`:


    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
         aggregate_multiple_processes: true
      }
    ]


You can also include child processes created by matching processes. Add the `include_child_processes` property, and set it to `true`. Any process whose parent matches `commandline` will be included in the summated metrics. This property is resursive; any children of the child processes will also be included. For example, to match all processes, and all child processes whose command line output matches the regular expression `java.*tomcat6`:


    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
         aggregate_multiple_processes: true,
         include_child_processes: true
      }
    ]


You can select a process by process identifier (PID), instead of a `commandline` regex. See [Configuration Options](#options) below.

To import metrics for more than one process, add a a separate `{...}` stanza for each, and set a uniqe `id`.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


4.\ Configure the process metrics dashboard for each `id`

Log into Scalyr and click Dashboards > Linux Process Metrics. The dropdowns at the top of the page let you select the `serverHost` and `process` of interest. (We map the `instance` field, discussed above, to the `process` dropdown).

Click `...` in upper right of the page, then select "Edit JSON". Find these lines near the top of the JSON file:

    // On the next line, list each "id" that you've used in a linux_process_metrics
    // clause in the Scalyr Agent configuration file (agent.json).
    values: [ "agent" ]

The "agent" id is used to report metrics for the Scalyr Agent itself. Add each `id` you created to the `values` list. For example, to add "tomcat":

    values: [ "agent", "tomcat" ]

Click "Save File". The dashboard only shows some of the data collected by this plugin. To view all data, go to Search view and query [monitor = 'linux_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27linux_process_metrics%27).

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).

<a name="options"></a>
## Configuration Options

| Property                       | Description | 
| ---                            | --- | 
| `module`                       | Always `scalyr_agent.builtin_monitors.linux_process_metrics` | 
| `id`                           | An id, included with each event. Shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin to import metrics from multiple processes. Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `commandline`                  | A regular expression, matching on the command line output of `ps aux`, to identify the process of interest. If multiple processes match, only the first will be used by default. See `aggregate_multiple_processes`, and `include_child_processes` to match on multiple processes. | 
| `aggregate_multiple_processes` | Optional (defaults to `false`). When `true`, *all* processes matched by `commandline` are included. Each metric is a summation of all matches. | 
| `include_child_processes`      | Optional (defaults to `false`). When `true`, all child processes matching `commandline` processes are included. Each metric is a summation of all processes (parent and children). This property is resursive; any children of the child process(es) are also included. | 
| `pid`                          | Process identifier. An alternative to `commandline` to specify a process. Ignored if `commandline` is set. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always `linux_process_metrics`. | 
| `instance` | The `id` value from Step **2**, e.g. `tomcat`. | 
| `app`      | Same as `instance`; created for compatibility with the original Scalyr Agent. | 
| `metric`   | Name of the metric, e.g. "app.cpu". | 
| `value`    | Value of the metric. | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:

| Metric                 | Fields               | Description | 
| ---                    | ---                  | --- | 
| `app.cpu`              | `type=user`          | User-mode CPU usage, in 1/100ths of a second. The value is cumulative since boot. | 
| `app.cpu`              | `type=system`        | System-mode CPU usage, in 1/100ths of a second. The value is cumulative since boot. | 
| `app.uptime`           |                      | Process uptime, in milliseconds. | 
| `app.threads`          |                      | Number of threads used by the process. | 
| `app.nice`             |                      | Nice priority value for the process. | 
| `app.mem.bytes`        | `type=vmsize`        | Bytes used by virtual memory. | 
| `app.mem.bytes`        | `type=resident`      | Bytes used by resident memory. | 
| `app.mem.bytes`        | `type=peak_vmsize`   | Peak virtual memory use, in bytes. | 
| `app.mem.bytes`        | `type=peak_resident` | Peak resident memory use, in bytes. | 
| `app.mem.majflt`       |                      | Number of page faults that require loading from disk. The value is cumulative since boot. | 
| `app.disk.bytes`       | `type=read`          | Bytes read from disk. The value is cumulative since boot. | 
| `app.disk.requests`    | `type=read`          | Number of disk read requests. The value is cumulative since boot. | 
| `app.disk.bytes`       | `type=write`         | Bytes written to disk. The value is cumulative since boot. | 
| `app.disk.requests`    | `type=write`         | Number of disk write requests. The value is cumulative since boot. | 
| `app.io.fds`           | `type=open`          | Number of open file descriptors. | 
| `app.io.wait`          |                      | Time waiting for I/O completion, in 1/100ths of a second. The value is cumulative since boot. | 
