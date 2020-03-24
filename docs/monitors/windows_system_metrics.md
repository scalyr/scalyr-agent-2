/// DECLARE path=/help/monitors/windows-system-metrics
/// DECLARE title=Windows System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

# Windows System Metrics:

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

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
