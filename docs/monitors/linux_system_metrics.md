/// DECLARE path=/help/monitors/linux-system-metrics
/// DECLARE title=Linux System Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

# Linux System Metrics

This agent monitor plugin records CPU consumption, memory usage, and other metrics for the server on which
the agent is running.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

The linux_system_metrics plugin is configured automatically by the Scalyr Agent. You do not need to include
this plugin in your configuration file.


## Viewing Data

You can see an overview of this data in the System dashboard. Click the {{menuRef:Dashboards}} menu and select
{{menuRef:System}}. Use the dropdown near the top of the page to select the host whose data you'd like to view.


## Log Reference

Each event recorded by this plugin will have the following fields:

|||# Field                    ||| Meaning
|||# ``monitor``              ||| Always ``linux_system_metrics``
|||# ``metric``               ||| The name of a metric being measured, e.g. "app.cpu"
|||# ``value``                ||| The metric value

Some metrics have additional fields, as documented below.
