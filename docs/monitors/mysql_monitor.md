/// DECLARE path=/help/monitors/mysql
/// DECLARE title=MySQL Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# MySQL Monitor

This agent monitor plugin records performance and usage data from a MySQL server.

NOTE: the MySQL monitor requires Python 2.6 or higher. (This applies to the server on which the Scalyr Agent
is running, which needn't necessarily be the same machine where the MySQL server is running.) If you need
to monitor MySQL from a machine running an older version of Python, [let us know](mailto:support@scalyr.com).

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

To configure the MySQL monitor plugin, you will need the following information:

- A MySQL username with administrative privileges. The user needs to be able to query the information_schema table,
  as well as assorted global status information.
- The password for that user.

Here is a sample configuration fragment:

    monitors: [
      {
         module:            "scalyr_agent.builtin_monitors.mysql_monitor",
         database_socket:   "default",
         database_username: "USERNAME",
         database_password: "PASSWORD"
      }
    ]

This configuration assumes that MySQL is running on the same server as the Scalyr Agent, and is using the default
MySQL socket. If not, you will need to specify the server's socket file, or hostname (or IP address) and port number;
see Configuration Reference.


## Viewing Data

After adding this plugin to the agent configuration file, wait one minute for data to begin recording. Then
click the {{menuRef:Dashboards}} menu and select {{menuRef:MySQL}}. (The dashboard may not be listed until
the agent begins sending MySQL data.) You will see an overview of MySQL performance statistics across all
servers where you are running the MySQL plugin. Use the {{menuRef:ServerHost}} dropdown to show data for a
specific server.

The dashboard shows only some of the data collected by the MySQL monitor plugin. To explore the full range
of data collected, go to the Search page and search for [$monitor = 'mysql_monitor'](/events?filter=$monitor%20%3D%20%27mysql_monitor%27).
This will show all data collected by this plugin, across all servers. You can use the {{menuRef:Refine search by}}
dropdown to narrow your search to specific servers and monitors.

The [View Logs](/help/view) page describes the tools you can use to view and analyze log data.
[Query Language](/help/query-language) lists the operators you can use to select specific metrics and values.
You can also use this data in [Dashboards](/help/dashboards) and [Alerts](/help/alerts).

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
