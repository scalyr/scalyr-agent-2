/// DECLARE path=/help/monitors/shell
/// DECLARE title=Shell Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# Shell Monitor

This agent monitor plugin periodically executes a specified shell command, and records the output.
It can be used to monitor any information that can be retrieved via a shell command. Shell commands
are run from the Scalyr Agent, and execute as the same user as the agent.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

Here is a simple configuration fragment showing use of the shell_monitor plugin. This sample will record
the version of the Linux kernel in use on the machine where the agent is running.

    monitors: [
      {
        module:  "scalyr_agent.builtin_monitors.shell_monitor",
        id:      "kernel-version",
        command: "uname -r"
      }
    ]

To record output from more than one command, use several copies of the shell_monitor plugin in your configuration.


## Viewing Data

After adding this plugin to the agent configuration file, wait one minute for data to begin recording. Then go to
the Search page and search for [$monitor = 'shell_monitor'](/events?filter=$monitor%20%3D%20%27shell_monitor%27).
This will show all data collected by this plugin, across all servers. You can use the {{menuRef:Refine search by}}
dropdown to narrow your search to specific servers and monitors.

The [View Logs](/help/view) page describes the tools you can use to view and analyze log data.
[Query Language](/help/query-language) lists the operators you can use to select specific metrics and values.
You can also use this data in [Dashboards](/help/dashboards) and [Alerts](/help/alerts).

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
