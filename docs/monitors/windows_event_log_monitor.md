/// DECLARE path=/help/monitors/windows-event-log-monitor
/// DECLARE title=Windows Event Log Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# Window Event Log Monitor

The Windows Event Log monitor uploads messages from the Windows Event Log to the Scalyr servers.
It can listen to multiple different event sources and also filter by messages of a certain type.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

On versions of Windows prior to Vista, the older EventLog API is used.  This API is unable to
retrieve 'Critical' events because this event type was only introduced in Vista.

On versions of Windows from Vista onwards, the newer Evt API is used which can be used to retrieve
'Critical' events.


## Sample Configuration

### Windows Vista and later

On Windows Vista and later, the Scalyr agent uses the EvtLog API, and you can configure it to query events on any 
channel, using the standard XPath query mechanism.  See the 
[Event log](https://msdn.microsoft.com/en-us/library/windows/desktop/dd996910.aspx) documentation for more
details.

For example, the following will configure the agent to listen to Critical, Error and Warning level events from the
Application, Security and System channels:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]

Alternatively, here is a configuration that will log critical errors for the Application channel, and critical, error
and warning messages for System and Security channels.

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Application"],
              "query": "*[System/Level=1]"
            },
            {
              "channel": ["Security", "System" ],
              "query": "*[System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]

### Windows Server 2003

For Windows versions earlier than Vista, the Scalyr agent will use the older Event Log API.

This sample will configure the agent running on Windows Server 2003 to listen to Error and Warning level events from 
the Application, Security and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        event_types:             "Error, Warning",
      }
    ]


## Configuration Reference

Here is the list of all configuration options you may use to config the Windows Event Log monitor:

|||# Option                        ||| Usage
|||# ``module``                    ||| Always ``scalyr_agent.builtin_monitors.windows_event_log_monitor``
|||# ``sources``                   ||| Optional (defaults to ``Application, Security, System``). A comma separated \
                                       list of event sources. You can use this to specify which event sources you are \
                                       interested in listening to. (Not valid for Vista and later.  Please use the \
                                       "channels" parameter instead.)
|||# ``event_types``               ||| Optional (defaults to ``All``). A comma separated list of event types to \
                                       log. Valid values are: All, Error, Warning, Information, AuditSuccess and \
                                       AuditFailure (Not valid for Vista and later.  Please use the "channels" \
                                       parameter instead.)
|||# ``channels``                  ||| Optional (defaults to ``[ {"channel" : ["Application", "Security", "System"], "query": "*"}]`` \
                                       A list of dict objects specifying a list of channels and an XPath query for \
                                       those channels. (Only available on Windows Vista and later.)
|||# ``maximum_records_per_source``||| Optional (defaults to ``10000``). The maximum number of records to read from \
                                       the end of each log sourceper gather_sample.
|||# ``error_repeat_interval``     ||| Optional (defaults to ``300``). The number of seconds to wait before logging \
                                       similar errors in the event log.
|||# ``server_name``               ||| Optional (defaults to ``localhost``). The remote server where the event log is \
                                       to be opened.


## Log reference:

Each event recorded by this plugin will have the following fields:

|||# Field             ||| Meaning
|||# ``monitor``       ||| Always ``windows_event_log_monitor``.
|||#``Source``         ||| The event source name, taken from the Windows field ``event.SourceName``.
|||#``RecordNumber``   ||| The event record number, taken from the Windows field ``event.RecordNumber``.
|||#``TimeGenerated``  ||| The time the event was generated.
|||#``TimeWritten``    ||| The time the event was written to the event log.
|||#``Type``           ||| The event type.
|||#``EventId``        ||| The event id, taken from the Windows field ``event.EventID``.
|||#``Category``       ||| The event category, taken from the Windows field ``event.EventCategory``.
|||#``EventMsg``       ||| The contents of the event message from the Windows Event Log.


