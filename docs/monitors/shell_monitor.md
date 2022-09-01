/// DECLARE path=/help/monitors/shell
/// DECLARE title=Shell Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Shell Agent Plugin

Execute a shell command, and import the output.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can import any information retrieved from a shell command. Commands execute as the same user as the Scalyr Agent.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the host that will execute the shell command.


2\. Configure the Scalyr Agent to import the output of a shell command

Open the Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for shell command:

    monitors: [
     {
       module:  "scalyr_agent.builtin_monitors.shell_monitor",
       id:      "kernel-version",
       command: "uname -r"
     }
    ]

The `command` property is the shell command you wish to execute. The `id` property lets you identify the command, and shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin, to import output from multiple shell commands. To add multiple shell commands, add a separate `{...}` stanza for each.

By default, only the first line of the command output is imported. Add and set `log_all_lines: true` if you wish to import the full output.

See [Configuration Options](#options) below for more properties you can add. You can set the number of characters to import, and you can apply a regular expression with a matching group, to extract data of interest from the output.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to begin sending data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr. From Search view query [monitor = 'shell_monitor'](/events?filter=monitor%3D%27shell_monitor%27). This will show all data collected by this plugin, across all servers.

For help, contact Support.

<a name="options"></a>
## Configuration Options

| Property         | Description | 
| ---              | --- | 
| `module`         | Always ``scalyr_agent.builtin_monitors.shell_monitor`` | 
| `id`             | An id, included with each event. Shows in the UI as a value for the `instance` field. Lets you distinguish between values recorded by multiple instances of this plugin (to run multiple shell commands). Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `command`        | The shell command to execute. | 
| `extract`        | Optional (defaults to ). A regular expression, applied to the command output. Lets you extract the data of interest. Must include a matching group (i.e. a subexpression enclosed in parentheses). Only the content of the matching group is imported. | 
| `log_all_lines`  | Optional (defaults to `false`). If `true`, this plugin imports the full output of the command. If `false`, only the first line is imported. | 
| `max_characters` | Optional (defaults to 200). Maximum number of characters to import from the command's output. A value up to 10000 may be set, but we currently truncate all fields to 3500 characters. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field       | Description | 
| ---         | --- | 
| `monitor`   | Always shell_monitor`. | 
| `instance`  | The `id` value from the configuration, for example `kernel-version`. | 
| `command`   | The shell command for this plugin instance, for example `uname -r`. | 
| `metric`    | Always `output`. | 
| `value`     | The output of the shell command, for example `3.4.73-64.112.amzn1.x86_64`. | 
| `length`    | Length of the output, for example `26`. | 
| `duration`  | Seconds spent executing the command. | 
| `exit_code` | Exit code for the shell command. | 
