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

Open the `agent.json` configuration file, located at `C:\Program Files (x86)\Scalyr\Config`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for the windows event log:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.windows_event_log_monitor",
      }
    ]


### Windows Vista and Later

You can configure the EvtLog API to query events on any channel with XPath. See the
[Event log](https://msdn.microsoft.com/en-us/library/windows/desktop/dd996910.aspx) documentation for more
details. For example:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]

`channels` is a list of `{...}` dict objects, each with `channel` and `query` properties. When not set it defaults to `[ {"channel" : ["Application", "Security", "System"], "query": "*"}]`, which imports all events from the Application, Security, and System channels.

The `channel` property is a list of channels to import events from, and the `query` property is an XPath expression. Events matching the `query`, from the channels in `channel`, are imported. In the above example, the Agent will import Critical (1), Error (2), Warning (3), and Information (4) events from the Application, Security and System channels.

This example imports Critical (1) events for the Application channel; and Critical (1), Error (2), and Warning (3) events for the System and Security channels:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Application"],
              "query": "*[System/Level=1]"
            },
            {
              "channel": ["Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]


You can also select events with the `<Channel>` tag, in the XML of an event. Go to:

    Run > eventvwr.msc > *select event you want to import* > Event Properties > Details > Select XML

For example, Microsoft-Windows-AAD/Operational events have the tag:

    <Channel>Microsoft-Windows-AAD/Operational</Channel>

To configure the Agent to listen to Critical (1), Error (2), Warning (3), and Information (4) events from this channel:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Microsoft-Windows-AAD/Operational"],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]


### Windows Server 2003

For Windows versions earlier than Vista, the Agent uses the older Event Log API.

This example configures the Agent, running on Windows Server 2003, to import Error and Warning level events from
the Application, Security and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        event_types:             "Error, Warning",
      }
    ]

`sources` is a comma separated list of event sources to import events from. It defaults to `Application, Security, System`. `event_types` is a comma separated list of event types to import. Valid values are: `All` (the default), `Error`, `Warning`, `Information`, `AuditSuccess` and `AuditFailure`. In the above example, only Error and Warning events from Application, Security, and System sources are imported.


3\. (Optional) Set more configuration options

You can format imported events as JSON. Simply add and set `json: true` in the configuration file. For example:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        json: true,
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]


See [Configuration Options](#options) below for more options. You can set a remote domain, server, username, and password; the number of records to read from the end of each log source; and the time to wait before logging similar errors.


4\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for data to send.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into DataSet and query [monitor = 'windows_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27windows_event_log%27). This will show all data collected by this plugin, across all servers.

<a name="options"></a>
## Configuration Options

| Property                       | Description | 
| ---                            | --- | 
| `module`                       | Always `scalyr_agent.builtin_monitors.windows_event_log_monitor` | 
| `sources`                      | Optional (defaults to `Application, Security, System`). A comma separated list of sources to import events from. (Not valid for Vista and later; use `channels` instead.) | 
| `event_types`                  | Optional (defaults to `All`). A comma separated list of event types to import. Valid values are: `All`, `Error`, `Warning`, `Information`, `AuditSuccess`, and `AuditFailure`. (Not valid for Vista and later; use `channels` instead.) | 
| `channels`                     | Optional (defaults to `[{"channel" : ["Application", "Security", "System"], "query": "*"}]`). A list of dict objects specifying a list of channels, and an XPath query for those channels. (Only available on Windows Vista and later.) | 
| `maximum_records_per_source`   | Optional (defaults to `10000`). Maximum number of records to read from the end of each log source per gather_sample. | 
| `error_repeat_interval`        | Optional (defaults to `300`). Number of seconds to wait before logging similar errors in the event log. | 
| `server_name`                  | Optional (defaults to `localhost`). The remote server to import events from. | 
| `remote_user`                  | Optional (defaults to `none`). Username for authentication on the remote server. This option is only valid on Windows Vista and above. | 
| `remote_password`              | Optional (defaults to `none`). Password to use for authentication on the remote server.  This option is only valid on Windows Vista and above. | 
| `remote_domain`                | Optional (defaults to `none`). The domain for the remote user account. This option is only valid on Windows Vista and above. | 
| `json`                         | Optional (defaults to `false`). Format events as json? Supports inclusion of all event fields. This option is only valid on Windows Vista and above. | 
| `placeholder_render`           | Optional (defaults to `false`). Render %%n placeholders in event data? This option is only valid on Windows Vista and above. | 
| `dll_handle_cache_size`        | Optional (defaults to `10`). DLL handle cache size, applicable only if `placeholder_render` is set. This option is only valid on Windows Vista and above. | 
| `placeholder_param_cache_size` | Optional (defaults to `1000`). Placeholder parameter cache size, applicable only if `placeholder_render` is set. This option is only valid on Windows Vista and above. | 
| `dll_handle_cache_ttl`         | Optional (defaults to `86400` ie 24 hours). DLL handle cache TTL, applicable only if `placeholder_render` is set. This option is only valid on Windows Vista and above. | 
| `placeholder_param_cache_ttl`  | Optional (defaults to `86400` ie 24 hours). Placeholder parameter cache TLL, applicable only if `placeholder_render` is set. This option is only valid on Windows Vista and above. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field           | Description | 
| ---             | --- | 
| `monitor`       | Always `windows_event_log_monitor`. | 
| `Channel`       | The event channel name, taken from the `Event.System.Channel` field. Only for Vista and above; see `Source` for pre-Vista versions. | 
| `EventRecordID` | The event record number, taken from the `Event.System.EventRecordID` field. Only for Vista and above; see `RecordNumber` for pre-Vista versions. | 
| `SystemTime`    | The time the event was generated, taken from the `Event.System.TimeCreated.SystemTime` field. Only for Vista and above; see `RecordNumber` for pre-Vista versions. | 
| `EventId`       | The event id, taken from the `Event.System.EventID` field on Vista and above, and from `event.EventID` for pre-Vista versions. | 
| `Source`        | The event source name, taken from the `event.SourceName` field. Only for pre-Vista versions of Windows; see `Channel` for Vista and above. | 
| `RecordNumber`  | The event record number, taken from the `event.RecordNumber` field. Only for pre-Vista versions of Windows; see `SystemTime` for Vista and above. | 
| `TimeGenerated` | The time the event was generated. Only for pre-Vista versions of Windows; see `SystemTime` for Vista and above. | 
| `Type`          | The event type. Only for pre-Vista versions of Windows. | 
| `Category`      | The event category, taken from the `event.EventCategory` field. Only for pre-Vista versions of Windows. | 
| `EventMsg`      | The contents of the event message from the Windows Event Log. Only for pre-Vista versions of Windows. | 
