/// DECLARE path=/help/monitors/windows-event-log-monitor
/// DECLARE title=Windows Event Log Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Windows Event Log

Import messages from the Windows Event Log.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can import events from multiple channels or sources, for example Application, Security, and System events. You can also filter by event type, for example "System/Level=0" events.

On Windows versions before Vista, 'Critical' events do not exist, and the older EventLog API is used. From Vista onwards, the newer Evt API is used.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Windows server.


2\. Configure the Scalyr Agent to import Event Logs

Open the Scalyr Agent configuration file, located at `C:\Program Files (x86)\Scalyr
