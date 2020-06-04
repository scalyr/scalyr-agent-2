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
    "Optional (defaults to /var/log/journal). Location on the filesystem of the journald logs.",
    convert_to=six.text_type,
    default="/var/log/journal",
)

define_config_option(
    __monitor__,
    "journal_poll_interval",
    "Optional (defaults to 5). The number of seconds to wait for data while polling the journal file. "
    "Fractional values are supported. Note: This values overrides the sample_interval of the monitor",
    convert_to=float,
    default=5,
)

define_config_option(
    __monitor__,
    "journal_fields",
    "Optional dict containing a list of journal fields to include with each message, as well as a field name to map them to.\n"
    "Note: Not all fields need to exist in every message and only fields that exist will be included.\n"
    "Defaults to {:\n"
    '  "_SYSTEMD_UNIT": "unit"\n'
    '  "_PID": "pid"\n'
    '  "_MACHINE_ID": "machine_id"\n'
    '  "_BOOT_ID": "boot_id"\n'
    '  "_SOURCE_REALTIME_TIMESTAMP": timestamp"\n'
    # Note, we dont' include the _HOSTNAME field as this is likely already specified by the serverHost variable
    # and so there's no need to duplicate this information.  If needed, this can be manually specified in the
    # plugin configuration.
    "}\n",
    default=None,
)

define_config_option(
    __monitor__,
    "journal_matches",
    "Optional list containing 'match' strings for filtering entries."
    'A match string follows the pattern  "FIELD=value" where FIELD is a field of '
    'the journal entry e.g. _SYSTEMD_UNIT, _HOSTNAME, _GID and "value" is the value '
    'to filter that field on, so a match string equal to "_SYSTEMD_UNIT=ssh.service" '
    "would filter query results to make sure that all entries entries originated from "
    "the `ssh.service` system unit. "
    "The journald monitor calls the journal reader method `add_match` for each string in this list. "
    "See the journald documentation for details on how the filtering works: "
    "https://www.freedesktop.org/software/systemd/python-systemd/journal.html#systemd.journal.Reader.add_match "
    "If this config item is empty or None then no filtering occurs.",
    default=None,
)

define_config_option(
    __monitor__,
    "id",
    "Optional id used to differentiate between multiple journald monitors. "
    "This is useful for configurations that define multiple journald monitors and that want to save unique checkpoints for each "
    "monitor.  If specified, the id is also sent to the server along with other attributes under the `monitor_id` field",
    convert_to=six.text_type,
    default="",
)

define_config_option(
    __monitor__,
    "staleness_threshold_secs",
    "When loading the journal events from a checkpoint, if the logs are older than this threshold, then skip to the end.",
    convert_to=int,
    default=10 * 60,
)

define_config_option(
    __monitor__,
    "max_log_rotations",
    "How many rotated logs to keep before deleting them, when writing journal entries to a log for sending to Scalyr.",
    convert_to=int,
    default=2,
)

define_config_option(
    __monitor__,
    "max_log_size",
    "Max size of a log file before we rotate it out, when writing journal entries to a log for sending to Scalyr.",
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
    """
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
    """

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
                fixed_field_name = scalyr_logging.AgentLogger.force_valid_metric_or_field_name(
                    field_name, is_metric=False
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
        self.log_config = self.log_manager.get_config(".*")

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
                extra = self._get_extra_fields(entry)
                unit = extra.get("unit", "")
                logger = self.log_manager.get_logger(unit)
                config = self.log_manager.get_config(unit)
                logger.info(self.format_msg(msg, config, extra))
                self._last_cursor = entry.get("__CURSOR", None)
            except Exception as e:
                global_log.warn(
                    "Error getting journal entries: %s" % six.text_type(e),
                    limit_once_per_x_secs=60,
                    limit_key="journald-entry-error",
                )

    def format_msg(
        self, message, log_config, extra_fields=None,
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
