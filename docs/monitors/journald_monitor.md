<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Journald

A Scalyr agent monitor that imports log entries from journald.

The journald monitor polls systemd journal files every ``journal_poll_interval`` seconds
and uploads any new entries to the Scalyr servers.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

By default, the journald monitor logs all log entries, but it can also be configured to filter entries by specific
fields.

## Dependencies

The journald monitor has a dependency on the Python systemd library, which is a Python wrapper around the systemd C API.
You need to ensure this library has been installed on your system in order to use this monitor, otherwise a warning
message will be printed if the Scalyr Agent is configured to use the journald monitor but the systemd library cannot be
found.

You can install the systemd Python library via package manager e.g.:

    apt-get install python-systemd  (debian/ubuntu)
    dnf install python-systemd  (CentOS/rhel/Fedora)

Or install it from source using pip e.g.

    pip install systemd-python

See here for more information: https://github.com/systemd/python-systemd/

## Sample Configuration

The following example will configure the agent to query the journal entries
located in /var/log/journal (the default location for persisted journald logs)

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.journald_monitor",
      }
    ]

Here is an example that queries journal entries from volatile/non-persisted journals, and filters those entries to only
include ones that originate from the ssh service

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.journald_monitor",
        journal_path: "/run/log/journal",
        journal_matches: ["_SYSTEMD_UNIT=ssh.service"]
      }
    ]

## Polling the Journal File

The journald monitor polls the journal file every ``journal_poll_interval`` seconds to check for new logs.  It does this by
creating a polling object (https://docs.python.org/2/library/select.html#poll-objects) and calling the ``poll`` method
of that object.  The ``poll`` method is called with a 0 second timeout so it never blocks.
After processing any new events, or if there are no events to process, the monitor thread sleeps for ``journal_poll_interval``
seconds and then polls again.

<a name="options"></a>
## Configuration Options

| Property                   | Description | 
| ---                        | --- | 
| `journal_path`             | Optional (defaults to /var/log/journal). Location of the journald logs in the filesystem. | 
| `journal_poll_interval`    | Optional (defaults to 5). The number of seconds to wait for data while polling the journal file. Fractional values are supported. Note: This values overrides the sample_interval of the monitor. | 
| `journal_fields`           | Optional. A dict of journal fields to upload with each message, and a field name to map them to. Note: Not all fields need exist in every message, and only fields that exist will be included. Defaults to { "_SYSTEMD_UNIT": "unit", "_PID": "pid", "_MACHINE_ID": "machine_id", "_BOOT_ID": "boot_id", "_SOURCE_REALTIME_TIMESTAMP": "timestamp" } | 
| `journal_matches`          | Optional. A list of "match strings" to filter entries on. A match string follows the pattern  "FIELD=value", where FIELD is a field of the journal entry, e.g. `_SYSTEMD_UNIT` or `_HOSTNAME`, and "value" is the value to filter that field on. For example, "_SYSTEMD_UNIT=ssh.service" only imports entries from the `ssh.service` system unit. The journald monitor calls the journal reader method `add_match` for each string in this list. See the [add_match documentation](https://www.freedesktop.org/software/systemd/python-systemd/journal.html#systemd.journal) for more information. If this property is empty or None, then no filtering occurs. | 
| `id`                       | An optional id for the monitor. This is useful when multiple journald monitors are specified, and you want to save unique checkpoints for each monitor. When specified, the id shows in the UI as the `monitor_id` field'. | 
| `staleness_threshold_secs` | Optional (defaults to `600` seconds). When loading the journal events from a checkpoint, if the logs are older than this threshold, then skip to the end. | 
| `max_log_rotations`        | Optional (defaults to `2`). How many rotated logs to keep before deleting them, when writing journal entries to a log for import. | 
| `max_log_size`             | Optional (defaults to `20MB`). Max size of a log file before we rotate it out, when writing journal entries to a log for import. | 
