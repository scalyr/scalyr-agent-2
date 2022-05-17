# Copyright 2018 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------
# author:  Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

if False:  # NOSONAR
    from typing import Dict

import datetime
import os
import re
import select
import threading
import traceback

import six

try:
    from systemd import journal
except ImportError:
    # We throw exception later during run time. This way we can still use print_monitor_docs.py
    # script without systemd dependency being installed
    journal = None

from scalyr_agent import ScalyrMonitor, define_config_option
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
import scalyr_agent.util as scalyr_util
from scalyr_agent.builtin_monitors.journald_utils import (
    LogConfigManager,
    JournaldLogFormatter,
)

global_log = scalyr_logging.getLogger(__name__)
__monitor__ = __name__

define_config_option(
    __monitor__,
    "journal_path",
    "Optional (defaults to `/var/log/journal`). Location of the journald logs in the filesystem.",
    convert_to=six.text_type,
    default="/var/log/journal",
)

define_config_option(
    __monitor__,
    "journal_poll_interval",
    "Optional (defaults to `5`). The number of seconds to wait for data while polling the journal file. Fractional values are supported. Note: This value overrides the `sample_interval` of the monitor.",
    convert_to=float,
    default=5,
)

define_config_option(
    __monitor__,
    "journal_fields",
    'Optional. A dict of journal fields to upload with each message, and a field name to map them to. Note: Not all fields need exist in every message, and only fields that exist will be included. Defaults to { "_SYSTEMD_UNIT": "unit", "_PID": "pid", "_MACHINE_ID": "machine_id", "_BOOT_ID": "boot_id", "_SOURCE_REALTIME_TIMESTAMP": "timestamp" }',
    # Note, we dont' include the _HOSTNAME field as this is likely already specified by the serverHost variable
    # and so there's no need to duplicate this information.  If needed, this can be manually specified in the
    # plugin configuration.
    default=None,
)

define_config_option(
    __monitor__,
    "journal_matches",
    'Optional. A list of "match strings" to filter entries on. A match string follows the pattern  "FIELD=value", where FIELD is a field of the journal entry, e.g. `_SYSTEMD_UNIT` or `_HOSTNAME`, and "value" is the value to filter that field on. For example, "_SYSTEMD_UNIT=ssh.service" only imports entries from the `ssh.service` system unit. The journald monitor calls the journal reader method `add_match` for each string in this list. See the [add_match documentation](https://www.freedesktop.org/software/systemd/python-systemd/journal.html#systemd.journal) for more information. If this property is empty or None, then no filtering occurs.',
    default=None,
)

define_config_option(
    __monitor__,
    "id",
    "An optional id for the monitor. Shows in the UI as the `monitor_id` field. "
    "Useful if you are running multiple instances of this plugin, "
    "and you want to save unique checkpoints for each monitor. You can add "
    "a separate `{...}` stanza for each instance the configuration file (`/etc/scalyr-agent-2/agent.json`).",
    convert_to=six.text_type,
    default="",
)

define_config_option(
    __monitor__,
    "staleness_threshold_secs",
    "Optional (defaults to `600` seconds). When loading the journal events from a checkpoint, if the logs are older than this threshold, then skip to the end.",
    convert_to=int,
    default=10 * 60,
)

define_config_option(
    __monitor__,
    "max_log_rotations",
    "Optional (defaults to `2`). How many rotated logs to keep before deleting them, when writing journal entries to a log for import.",
    convert_to=int,
    default=2,
)

define_config_option(
    __monitor__,
    "max_log_size",
    "Optional (defaults to `20MB`). Max size of a log file before we rotate it out, when writing journal entries to a log for import.",
    convert_to=int,
    default=20 * 1024 * 1024,
)

# this lock must be held to access the
# _global_checkpoints dict
_global_lock = threading.Lock()

_global_checkpoints = {}  # type: Dict[str, Checkpoint]


def verify_systemd_library_is_available():
    """
    Throw an exception if systemd library is not available.
    """
    if not journal:
        raise ImportError(
            "Python systemd library not installed.\n\nYou must install the systemd python library in order "
            "to use the journald monitor.\n\nThis can be done via package manager e.g.:\n\n"
            "  apt-get install python-systemd  (debian/ubuntu)\n"
            "  dnf install python-systemd  (CentOS/rhel/Fedora)\n\n"
            "or installed from source using pip e.g.\n\n"
            "  pip install systemd-python\n\n"
            "See here for more info: https://github.com/systemd/python-systemd/\n"
        )


def load_checkpoints(filename):
    """
    Atomically loads checkpoints from a file.  The checkpoints are only ever loaded from disk once,
    and any future calls to this function return the in-memory checkpoints of the first successfully completed call.
    @param filename: the path on disk to a JSON file to load checkpoints from
    """
    result = None
    _global_lock.acquire()
    try:
        if filename in _global_checkpoints:
            result = _global_checkpoints[filename]
    finally:
        _global_lock.release()

    # if checkpoints already exist for this file, return the in memory copy
    if result is not None:
        return result

    # read from the file on disk
    checkpoints = {}
    try:
        checkpoints = scalyr_util.read_file_as_json(filename, strict_utf8=True)
    except Exception:
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "No checkpoint file '%s' exists.\n\tAll journald logs will be read starting from their current end.",
            filename,
        )
        checkpoints = {}

    _global_lock.acquire()
    try:
        # check if another thread created Checkpoints for this file
        # while we were loading from disk and if so, return
        # the in memory copy
        if filename in _global_checkpoints:
            result = _global_checkpoints[filename]
        else:
            # checkpoints for this file haven't been created yet, so
            # create them and store them in the global checkpoints dict
            result = Checkpoint(filename, checkpoints)
            _global_checkpoints[filename] = result
    finally:
        _global_lock.release()

    return result


class Checkpoint(object):
    """
    This class atomically gets and sets a series of checkpoints, where
    a checkpoint is a key=value pair, and handles writing the checkpoints
    atomically to disk.
    It can be used when multiple threads (e.g. multiple monitors) need to
    load and save checkpoints to disk, and want to group checkpoints in a single file
    rather than each thread/monitor writing to its own file.

    To ensure that checkpoint objects are atomically loaded from disk, Checkpoint objects
    should not be created manually, rather they should be created through a call to `load_checkpoints`.
    """

    def __init__(self, filename, checkpoints):
        # this lock must be held to access/change self._checkpoints
        self._lock = threading.Lock()
        self._filename = filename
        self._checkpoints = checkpoints

    def get_checkpoint(self, name):
        """
        Return the checkpoint for the specified name, or None if no checkpoint exists
        @param name: the name of the checkpoint
        """
        result = None
        self._lock.acquire()
        try:
            result = self._checkpoints.get(name, None)
        finally:
            self._lock.release()

        return result

    def update_checkpoint(self, name, value):
        """
        Update the value of the named checkpoint, and write the checkpoints to disk as JSON
        @param name: the name of the checkpoint
        @param value: the value to set the checkpoint to
        """
        self._lock.acquire()
        try:
            self._checkpoints[name] = value
            tmp_file = self._filename + "~"
            scalyr_util.atomic_write_dict_as_json_file(
                self._filename, tmp_file, self._checkpoints
            )
        finally:
            self._lock.release()


class JournaldMonitor(ScalyrMonitor):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    """
# Journald

Import log entries from journald.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running the journald daemon.


2\\. Install the `python-systemd` dependency

The `python-systemd` package is a wrapper for the `systemd` C API. See [https://github.com/systemd/python-systemd/](https://github.com/systemd/python-systemd/) for more information. If the Scalyr Agent cannot find this library, a warning message will show.

To install `python-systemd` on Debian or Ubuntu:

    apt-get install python-systemd

For CentOS/rhel/Fedora:

    dnf install python-systemd

You can also install from source with pip:

    pip install systemd-python


3\\. Configure the Scalyr Agent to import the journal file

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


4\\. Set parsers

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
           journald_unit: "ssh\\.service",
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


5\\. Set attributes, and other properties

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
           journald_unit: "ssh\\.service",
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


6\\. Override value escaping (optional)

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



7\\. Save and confirm

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
           journald_unit: "ssh\\.service",
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
    """
    # fmt: on

    def _initialize(self):
        verify_systemd_library_is_available()

        self._max_log_rotations = self._config.get("max_log_rotations")
        self._max_log_size = self._config.get("max_log_size")
        self._journal_path = self._config.get("journal_path")
        self._format_version = self._config.get("format_version")
        if len(self._journal_path) == 0:
            self._journal_path = None
        if self._journal_path and not os.path.exists(self._journal_path):
            raise BadMonitorConfiguration(
                "journal_path '%s' does not exist or is not a directory"
                % self._journal_path,
                "journal_path",
            )

        self._id = self._config.get("id")
        self._checkpoint_name = self.module_name
        # handle case where id is either None or empty
        if self._id:
            self._checkpoint_name = self._id

        data_path = ""

        if self._global_config:
            data_path = self._global_config.agent_data_path

        self._checkpoint_file = os.path.join(data_path, "journald-checkpoints.json")

        self._staleness_threshold_secs = self._config.get("staleness_threshold_secs")

        self._journal = None
        self._poll = None
        # override the sample_interval
        self.set_sample_interval(self._config.get("journal_poll_interval"))
        self.log_config["parser"] = "journald"

        self._extra_fields = self._config.get("journal_fields")
        if self._extra_fields is not None:
            for field_name in self._extra_fields:
                fixed_field_name = (
                    scalyr_logging.AgentLogger.force_valid_metric_or_field_name(
                        field_name, is_metric=False
                    )
                )
                if field_name != fixed_field_name:
                    self._extra_fields[fixed_field_name] = self._extra_fields[
                        field_name
                    ]
                    del self._extra_fields[fixed_field_name]

        self._last_cursor = None

        matches = self._config.get("journal_matches")
        if matches is None:
            matches = []

        match_re = re.compile("^([^=]+)=(.+)$")
        for match in matches:
            if not match_re.match(match):
                raise BadMonitorConfiguration(
                    "journal matchers expects the following format for each element: FIELD=value.  Found: %s"
                    % match,
                    "journal_matches",
                )

        self._matches = matches
        if self._extra_fields is None:
            self._extra_fields = {
                "_SYSTEMD_UNIT": "unit",
                "_PID": "pid",
                "_MACHINE_ID": "machine_id",
                "_BOOT_ID": "boot_id",
                "_SOURCE_REALTIME_TIMESTAMP": "timestamp",
            }

        # Closing the default logger since we aren't going to use it, instead allowing LogConfigManager to provide us
        # with loggers
        self._logger.closeMetricLog()
        self.log_manager = LogConfigManager(
            self._global_config,
            JournaldLogFormatter(),
            self._max_log_size,
            self._max_log_rotations,
        )
        self.log_config = self.log_manager.get_config({"unit": ".*"})

    def run(self):
        self.log_manager.set_log_watcher(self._log_watcher)
        self._checkpoint = load_checkpoints(self._checkpoint_file)
        self._reset_journal()
        ScalyrMonitor.run(self)

    def set_log_watcher(self, log_watcher):
        self._log_watcher = log_watcher

    def _reset_journal(self):
        """
        Closes any open journal and loads the journal file located at self._journal_path
        """
        try:
            if self._journal:
                self._journal.close()

            self._journal = None
            self._poll = None

            # open the journal, limiting it to read logs since boot
            self._journal = journal.Reader(path=self._journal_path)
            self._journal.this_boot()

            # add any filters
            for match in self._matches:
                self._journal.add_match(match)

            # load the checkpoint cursor if it exists
            cursor = self._checkpoint.get_checkpoint(self._checkpoint_name)

            skip_to_end = True

            # if we have a checkpoint see if it's current
            if cursor is not None:
                try:
                    self._journal.seek_cursor(cursor)
                    entry = self._journal.get_next()

                    timestamp = entry.get("__REALTIME_TIMESTAMP", None)
                    if timestamp:
                        current_time = datetime.datetime.utcnow()
                        delta = current_time - timestamp
                        if delta.total_seconds() < self._staleness_threshold_secs:
                            skip_to_end = False
                        else:
                            global_log.log(
                                scalyr_logging.DEBUG_LEVEL_0,
                                "Checkpoint is older than %d seconds, skipping to end"
                                % self._staleness_threshold_secs,
                            )
                except Exception as e:
                    global_log.warn(
                        "Error loading checkpoint: %s. Skipping to end."
                        % six.text_type(e)
                    )

            if skip_to_end:
                # seek to the end of the log
                # NOTE: we need to back up a single item, otherwise journald returns
                # random entries
                self._journal.seek_tail()
                self._journal.get_previous()

            # configure polling of the journal file
            self._poll = select.poll()
            mask = self._journal.get_events()
            self._poll.register(self._journal, mask)
        except Exception as e:
            global_log.warn(
                "Failed to reset journal %s\n%s"
                % (six.text_type(e), traceback.format_exc())
            )

    def _get_extra_fields(self, entry):
        """
        Build a dict of key->values based on the fields available in the
        passed in journal entry, and mapped to the keys in the 'journal_fields' config option.
        """
        result = {}

        for key, value in six.iteritems(self._extra_fields):
            if key in entry:
                result[value] = six.text_type(entry[key])

        if self._id and "monitor_id" not in result:
            result["monitor_id"] = self._id

        return result

    def _has_pending_entries(self):
        """
        Checks to see if there are any pending entries in the journal log
        that are ready for processing
        """

        # do nothing if there is nothing ready to poll
        # Note: we poll for 0 seconds, and therefore never block
        # the main monitor will block at the end of its
        # gather_sample method
        if not self._poll.poll(0):
            return False

        # see if there are any entries to process
        process = journal.NOP
        try:
            process = self._journal.process()
        except Exception as e:
            # early return if there was an error
            global_log.warn(
                "Error processing journal entries: %s" % six.text_type(e),
                limit_once_per_x_secs=60,
                limit_key="journald-process-error",
            )

            return False

        # If the result is a journal.NOP this means that the journal has not changed
        # since the last call to process(), which means we have no new entries waiting to
        # be read
        if process == journal.NOP:
            return False

        return True

    def _process_entries(self):
        """
        Processes all entries in the journal log.

        Note: This function should only be called directly after a call to _has_pending_entries()
        returns True.
        """
        # read all the entries
        for entry in self._journal:
            try:
                msg = entry.get("MESSAGE", "")
                fields = self._get_extra_fields(entry)
                logger = self.log_manager.get_logger(fields)
                config = self.log_manager.get_config(fields)
                logger.info(self.format_msg(msg, config, fields))
                self._last_cursor = entry.get("__CURSOR", None)
            except Exception as e:
                global_log.warn(
                    "Error getting journal entries: %s" % six.text_type(e),
                    limit_once_per_x_secs=60,
                    limit_key="journald-entry-error",
                )

    def format_msg(
        self,
        message,
        log_config,
        extra_fields=None,
    ):
        string_buffer = six.StringIO()

        detect_escaped_strings = False
        emit_raw_details = False
        if log_config:
            # If True, will attempt to see if the values are already escaped strings, and if so, not add in an
            # additional escaping ourselves
            detect_escaped_strings = log_config.get("detect_escaped_strings", False)
            # If True, will always emit values as their original string value instead of attempting to escaping them
            emit_raw_details = log_config.get("emit_raw_details", False)

        string_buffer.write(
            self._format_key_value(
                "%s %s", "details", message, emit_raw_details, detect_escaped_strings
            )
        )

        if extra_fields is not None:
            for field_name in sorted(extra_fields):
                string_buffer.write(
                    self._format_key_value(
                        " %s=%s",
                        field_name,
                        extra_fields[field_name],
                        False,
                        detect_escaped_strings,
                    )
                )

        msg = string_buffer.getvalue()
        string_buffer.close()
        return msg

    def _format_key_value(
        self, format, key, value, emit_raw_details, detect_escaped_strings
    ):
        if emit_raw_details or (
            detect_escaped_strings and value.startswith('"') and value.endswith('"')
        ):
            return format % (key, value)
        else:
            return format % (key, scalyr_util.json_encode(value))

    def gather_sample(self):

        if not self._has_pending_entries():
            return

        self._process_entries()

        if self._last_cursor is not None:
            self._checkpoint.update_checkpoint(
                self._checkpoint_name, six.text_type(self._last_cursor)
            )

    def stop(self, wait_on_join=True, join_timeout=5):
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)
        self.log_manager.close()
        self._logger.info("Stop was called on the journald monitor")
