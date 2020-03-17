
# Journald Monitor

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

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
