<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Journald

Import log entries from journald.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running the journald daemon.


2\. Install the `python-systemd` dependency

The `python-systemd` package is a wrapper for the `systemd` C API. See [https://github.com/systemd/python-systemd/](https://github.com/systemd/python-systemd/) for more information. If the Scalyr Agent cannot find this library, a warning message will show.

To install `python-systemd` on Debian or Ubuntu:

    apt-get install python-systemd

For CentOS/rhel/Fedora:

    dnf install python-systemd

You can also install from source with pip:

    pip install systemd-python


3\. Configure the Scalyr Agent to import the journal file

Open the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section, add a `{...}` stanza, and set the `module` property for journald.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.journald_monitor",
      }
    ]

This plugin creates a polling object (https://docs.python.org/2/library/select.html#poll-objects). A `poll` runs with a 0 second timeout - it never blocks. After processing new events, the thread sleeps for a period of time. By default, the journal file is polled for new logs every 5 seconds.

If your journal file is not at the default `/var/log/journal`, add the `journal_path` property to the `{...}` stanza, and set it. Here is an example that polls journal entries from volatile/non-persisted journals:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.journald_monitor",
        journal_path: "/run/log/journal",
        journal_matches: ["_SYSTEMD_UNIT=ssh.service"]
      }
    ]

The `journal_matches` property lets you to filter your journal entries. This property is an optional `[...]` list of "match strings", with the pattern "FIELD=value". FIELD is a field in the journal entry, for example `_SYSTEMD_UNIT`, and "value" is the value to filter that field on. In the above example, only entries from `ssh.service` are imported.

See [Configuration Options](#options) below for more properties you can add to the `monitors: [ ... ]` section.


4\. Set parsers

In the `agent.json` configuration file, add a top-level `journald_logs: [...]` array. [Modular Configuration](#modular) is supported - you can add this array to any `.json` file in the `agent.d` directory.

    journald_logs: [
      {
          journald_unit: ".*",
          parser: "journaldParser"
      }
    ]

`journald_unit` is a regular expression, matching on the journal entry's `_SYSTEMD_UNIT` field. It defaults to `.*`, matching all. Note that double-escaping regex elements is required - see [Regex](https://app.scalyr.com/help/regex) for more information.

The `parser` property creates a [configuration file](https://app.scalyr.com/parsers) in the UI. There you can set rules to parse fields from your journal entries, or you can click a button and we will create a parser for you.

You can set multiple parsers by adding a `{...}` stanza for each. For example, to assign `sshParser` to the logs from the SSH service, and `journaldParser` to the others:

    journald_logs: [
      {
           journald_unit: "ssh\.service",
           parser: "sshParser",
           rename_logfile: "/journald/ssh_service.log"
      },
      {
          journald_unit: ".*",
          parser: "journaldParser"
      }
    ]

The parser assigned is based on the first matching entry in the `journald_logs` array.  If you put the first stanza in the above example last, the SSH service will be assigned the "journaldParser", as it matches on `".*"`.

The `rename_logfile` property lets you to create a meaningful name for the log file. This file is auto-generated, with the syntax `/var/log/scalyr-agent-2/journald_XXXX.log`, where `XXXX` is a hash to guarantee the name is unique. In the example above, the SSH service is renamed to "/journald/ssh_service.log".

If you are using Docker and the `journald` log driver, `_SYSTEMD_UNIT` will always be `docker.service`. You can replace the `journald_unit` property with `journald_globs`. This property is a dict of globs, keyed by journald fields. All fields and values defined in `journald_globs` must be present for a match.

Keyed journald fields must also be added to the [journal_fields](#options) property in step **3** above. Only fields defined in this property are available for glob matching.

For example, to assign `sshParser` to the logs from the SSH service, you can use the `_COMM` field:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.journald_monitor",
        journal_path: "/run/log/journal",
        journal_fields: { "_COMM": "process", "_PID": "pid", "_MACHINE_ID": "machine_id", "_BOOT_ID": "boot_id", "_SOURCE_REALTIME_TIMESTAMP": timestamp" }
      }
    ]


    journald_logs: [
      {
          journald_globs: { "_COMM": "ssh" },
          parser: "sshParser"
      }
    ]


5\. Set attributes, and other properties

The `attributes` property lets you attach key-value pairs to your entries. These attributes become searchable fields in the UI, and are especially useful for determining the source of log data.

You can also add and set these properties:

| Property | Description |
|---|---|
| [sampling_rules](https://app.scalyr.com/help/scalyr-agent#filter)        | Import a random sample of logs matching a regular expression. Used to decrease log volume. |
| [exclude](https://app.scalyr.com/help/scalyr-agent#logExclusion)         | A list of glob patterns.  Any file that matches will not be imported. |
| [redaction_rules](https://app.scalyr.com/help/scalyr-agent#redaction)    | Rewrite or delete sensitive portions of a log. |
| [compression_type](https://app.scalyr.com/help/scalyr-agent#compressing) | Turn off or change the default `deflate` compression, applied to all imported logs. |

&nbsp;

Here is an example with attributes, redaction rules, and sampling rules set:

    journald_logs: [
      {
           journald_unit: "ssh\.service",
           parser: "sshParser",
           attributes: { "service": "ssh" },
           redaction_rules: [ { match_expression: "password", replacement: "REDACTED" } ],
           sampling_rules: [ { match_expression: "INFO", sampling_rate: 0.1} ],
      },
      {
          journald_unit: ".*",
          parser: "journaldParser",
          attributes: { "service": "unknown" }
      }
    ]


6\. Override value escaping (optional)

By default, several quoting and escaping rules are applied. In particular, we quote extracted fields and escape values. You may wish to override this behavior, depending on your journald entry format.

To override quoting and escaping of the journald `MESSAGE` field, add the `emit_raw_details` property, and set it to `true`. This will make parsing easier for messages that are already quoted, and special characters that are already escaped:

    journald_logs: [
      {
          journald_unit: ".*",
          emit_raw_details: true
      }
    ]

If `detect_escaped_strings` is `true`, all extracted fields, including `MESSAGE` and fields listed in `journal_fields`, will not be quoted and escaped *if* the first and last character of the field is a quote (`"`). This is useful if you expect any field to be quoted, and special characters escaped:

    journald_logs: [
      {
          journald_unit: ".*",
          detect_escaped_strings: true
      }
    ]



7\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log in to your Scalyr account and go to the [Logs](https://app.scalyr.com/logStart) overview page. A log file should show for each `journal_path` you set in step **3**.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


<a name="modular"></a>
## Modular Configuration

You may split your `journald_logs` JSON array across multiple files, similar to how the `logs` JSON array can be split across multiple [modular configuration files](https://app.scalyr.com/help/scalyr-agent#modularConfig), in the `agent.d` directory.

For example, you may have a file `journald_ssh.json` in `agent.d` with contents:

    journald_logs: [
      {
           journald_unit: "ssh\.service",
           parser: "sshParser",
           attributes: { "service": "ssh" },
           redaction_rules: [ { match_expression: "password", replacement: "REDACTED" } ],
           sampling_rules: [ { match_expression: "INFO", sampling_rate: 0.1} ],
      }
    ]

And a second file `zz_journald_defaults.json` with contents:

    journald_logs: [
      {
          journald_unit: ".*",
          parser: "journaldParser",
          attributes: { "service": "unknown" }
      }
    ]

The contents of the `journald_logs` JSON array will be computed by appending all `journald_logs` entries in all files in alphabetical order of their file names.  You can prefix a filename with `zz` to guarantee it will be the last entry in the `journald_logs` JSON array.

<a name="options"></a>
## Configuration Options

| Property                   | Description | 
| ---                        | --- | 
| `journal_path`             | Optional (defaults to `/var/log/journal`). Location of the journald logs in the filesystem. | 
| `journal_poll_interval`    | Optional (defaults to `5`). The number of seconds to wait for data while polling the journal file. Fractional values are supported. Note: This value overrides the `sample_interval` of the monitor. | 
| `journal_fields`           | Optional. A dict of journal fields to upload with each message, and a field name to map them to. Note: Not all fields need exist in every message, and only fields that exist will be included. Defaults to { "_SYSTEMD_UNIT": "unit", "_PID": "pid", "_MACHINE_ID": "machine_id", "_BOOT_ID": "boot_id", "_SOURCE_REALTIME_TIMESTAMP": "timestamp" } | 
| `journal_matches`          | Optional. A list of "match strings" to filter entries on. A match string follows the pattern  "FIELD=value", where FIELD is a field of the journal entry, e.g. `_SYSTEMD_UNIT` or `_HOSTNAME`, and "value" is the value to filter that field on. For example, "_SYSTEMD_UNIT=ssh.service" only imports entries from the `ssh.service` system unit. The journald monitor calls the journal reader method `add_match` for each string in this list. See the [add_match documentation](https://www.freedesktop.org/software/systemd/python-systemd/journal.html#systemd.journal) for more information. If this property is empty or None, then no filtering occurs. | 
| `id`                       | An optional id for the monitor. Shows in the UI as the `monitor_id` field. Useful if you are running multiple instances of this plugin, and you want to save unique checkpoints for each monitor. You can add a separate `{...}` stanza for each instance the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `staleness_threshold_secs` | Optional (defaults to `600` seconds). When loading the journal events from a checkpoint, if the logs are older than this threshold, then skip to the end. | 
| `max_log_rotations`        | Optional (defaults to `2`). How many rotated logs to keep before deleting them, when writing journal entries to a log for import. | 
| `max_log_size`             | Optional (defaults to `20MB`). Max size of a log file before we rotate it out, when writing journal entries to a log for import. | 
