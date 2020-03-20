/// DECLARE path=/help/monitors/windows-event-log-monitor
/// DECLARE title=Windows Event Log Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Window Event Log Monitor

The Windows Event Log monitor uploads messages from the Windows Event Log to the Scalyr servers.
It can listen to multiple different event sources and also filter by messages of a certain type.

On versions of Windows prior to Vista, the older EventLog API is used.  This API is unable to
retrieve 'Critical' events because this event type was only introduced in Vista.

On versions of Windows from Vista onwards, the newer Evt API is used which can be used to retrieve
'Critical' events.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

### Windows Vista and later

On Windows Vista and later, the Scalyr agent uses the EvtLog API, and you can configure it to query events on any channel, using the standard XPath query mechanism.  See: https://msdn.microsoft.com/en-us/library/windows/desktop/dd996910(v=vs.85).aspx

For example, the following will configure the agent to listen to Critical, Error and Warning level events from the Application, Security and System channels:

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

Alternatively, here is a configuration that will log critical errors for the Application channel, and critical, error and warning messages for System and Security channels.

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

This sample will configure the agent running on Windows Server 2003 to listen to Error and Warning level events from the Application, Security
and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        event_types:             "Error, Warning",
      }
    ]
## Configuration Reference

|||# Option                        ||| Usage
|||# ``module``                    ||| Always ``scalyr_agent.builtin_monitors.windows_event_log_monitor``
|||# ``sources``                   ||| Optional (defaults to ``Application, Security, System``). A comma separated \
                                       list of event sources.
You can use this to specify which event sources you are \
                                       interested in listening to.(Vista and later) Cannot be used.  Please use the \
                                       "channels" parameter instead.
|||# ``event_types``               ||| Optional (defaults to ``All``). A comma separated list of event types to \
                                       log.
Valid values are: All, Error, Warning, Information, AuditSuccess and \
                                       AuditFailure(Vista and later) Cannot be used.  Please use the "channels" \
                                       parameter instead.
|||# ``channels``                  ||| A list of dict objects specifying a list of channels and an XPath query for \
                                       those channels.
Only available on Windows Vista and later.
Optional (defaults \
                                       to ``[ {"channel" : ["Application", "Security", "System"], "query": "*"}]

|||# ``maximum_records_per_source``||| Optional (defaults to ``10000``). The maximum number of records to read from \
                                       the end of each log sourceper gather_sample.

|||# ``error_repeat_interval``     ||| Optional (defaults to ``300``). The number of seconds to wait before logging \
                                       similar errors in the event log.

|||# ``server_name``               ||| Optional (defaults to ``localhost``). The remote server where the event log is \
                                       to be opened

|||# ``remote_user``               ||| Optional (defaults to ``None``). The username to use for authentication on the \
                                       remote server.  This option is only valid on Windows Vista and above

|||# ``remote_password``           ||| Optional (defaults to ``None``). The password to use for authentication on the \
                                       remote server.  This option is only valid on Windows Vista and above

|||# ``remote_domain``             ||| Optional (defaults to ``None``). The domain to which the remote user account \
                                       belongs.  This option is only valid on Windows Vista and above
