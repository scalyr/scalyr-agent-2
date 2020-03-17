/// DECLARE path=/help/monitors/graphite
/// DECLARE title=Graphite Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# Graphite Monitor

This agent monitor plugin acts as a Graphite server, allowing you to import data from Graphite-compatible tools
into Scalyr.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

Here is a simple configuration fragment showing use of the url_monitor plugin. This sample will record
the instance type of the Amazon EC2 server on which the agent is running.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.graphite_monitor"
      }
    ]

By default, the plugin will listen for connecions on both of the standard Graphite TCP ports (2003 for
the "plain text" protocol, and 2004 for "pickle" protocol). For security, it will only accept connections
from localhost (i.e. from processes running on the same server). Set the configuration option ``only_accept_local``
to false to allow connections from other servers. You can also specify custom ports; see Configuration Reference.


## Viewing Data

After adding this plugin to the agent configuration file, wait one minute for the agent to open the Graphite
ports. Then configure your Graphite-compatible tools to send data to these ports.

Once you are sending Graphite data to the agent, go to the Search page and search for
[$monitor = 'graphite_monitor'](/events?filter=$monitor%20%3D%20%27graphite_monitor%27). This will show all Graphite
data imported by the agent, across all servers. You can use the {{menuRef:Refine search by}} dropdown to narrow your
search to specific servers and monitors.

The [View Logs](/help/view) page describes the tools you can use to view and analyze log data.
[Query Language](/help/query-language) lists the operators you can use to select specific metrics and values.
You can also use this data in [Dashboards](/help/dashboards) and [Alerts](/help/alerts).

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
