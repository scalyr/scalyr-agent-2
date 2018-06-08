
# Journald Monitor

A Scalyr agent monitor that imports log entries from journald.

The journald monitor polls systemd journal files every ``sample_interval`` seconds
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

## Configuration Reference

Here is the list of all configuration options in addition to the default options for each monitor that you may use to
config the journald monitor:

|||# Option                        ||| Usage
|||# ``module``                    ||| Always ``scalyr_agent.builtin_monitors.journald_monitor``
|||# ``journal_path``              ||| Optional (defaults to ``/var/log/journal``). Location on the filesystem of the journald logs.
|||# ``journal_poll_timeout``      ||| Optional (defaults to ``0``). The number of seconds to wait for data while polling \
                                       the journal file. Fractional values are supported up to millisecond accuracy. \
                                       Note: you are better off setting the sample_interval monitor option if the \
                                       timeout is longer than one second. For a detailed explanation, please see the \
                                       documentation section on polling.
|||# ``journal_fields``            ||| Optional dict containing journal fields to upload with each message, \
                                       as well as a field name to map them to on the Scalyr website. \
                                       Note: Not all fields need to exist in every message and only fields that exist will be included. \
                                       Defaults to ``{ "_SYSTEMD_UNIT": "unit", "_PID": "pid", "_MACHINE_ID": "machine_id", "_BOOT_ID": "boot_id", "_SOURCE_REALTIME_TIMESTAMP": timestamp" }``
|||# ``journal_matches``           ||| Optional list containing 'match' strings for filtering entries. \
                                       A match string follows the pattern  "FIELD=value" where FIELD is a field of \
                                       the journal entry e.g. _SYSTEMD_UNIT, _HOSTNAME, _GID and "value" is the value \
                                       to filter that field on, so a match string equal to "_SYSTEMD_UNIT=ssh.service" \
                                       would filter query results to make sure that all entries entries originated from \
                                       the ``ssh.service`` system unit. \
                                       The journald monitor calls the journal reader method ``add_match`` for each string in this list. \
                                       See the journald documentation for details on how the filtering works: \
                                       https://www.freedesktop.org/software/systemd/python-systemd/journal.html#systemd.journal.Reader.add_match \
                                       If this config item is empty or None then no filtering occurs.
|||# ``id``                        ||| Optional id used to differentiate between multiple journald monitors in the same agent.json configuration file. \
                                       This is useful for configurations that define multiple journald monitors and that want to save unique checkpoints for each \
                                       monitor.  If specified, the id is also sent to the server along with other attributes under the ``monitor_id`` field'.
|||# ``staleness_threshold_secs``  ||| Optional, defaults = ``600``.  When loading the journal events from a \
                                       checkpoint, if the logs are older than this threshold, then the monitor skips to \
                                       the end of the journal and only logs new entries.

## Polling the Journal File

The journald monitor polls the journal file every ``sample_interval`` seconds to check for new logs.  It does this by
creating a polling object (https://docs.python.org/2/library/select.html#poll-objects) and calling the ``poll`` method
of that object.  The ``poll`` method takes a timeout parameter that blocks the calling thread until there is data
available on the polling object or until the timeout expires.  This timeout parameter can be configured using the
``journal_poll_timeout`` configuration option.  By default, this option is 0, meaning that the calling thread never
blocks when polling the journal.  Instead the monitor only blocks at the end of its ``gather_sample`` method.

Setting the ``journal_poll_timeout`` option to a value greater than 0 means that the polling call will block inside the
``gather_sample`` method (and again at the end of the ``gather_sample``).  This may be useful in some situations, but
if the ``journal_poll_timeout`` is greater than 1 second, it is generally more useful to leave it at 0 and use the
``sample_interval`` configuration option instead.
