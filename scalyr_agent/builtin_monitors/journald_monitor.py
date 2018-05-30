# Copyright 2014 Scalyr Inc.
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

__author__ = 'imron@scalyr.com'

import datetime
import os
import re
import select
from scalyr_agent import ScalyrMonitor, define_config_option
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.monitor_utils import journald_checkpoints
from scalyr_agent.monitor_utils.journald_checkpoints import Checkpoint
import scalyr_agent.scalyr_logging as scalyr_logging

try:
    from systemd import journal
except ImportError:
    raise Exception('Python systemd library not installed.\n\nYou must install the systemd python library in order '
                    'to use the journald monitor.\n\nThis can be done via package manager e.g.:\n\n'
                    '  apt-get install python-systemd  (debian/ubuntu)\n'
                    '  dnf install python-systemd  (CentOS/rhel/Fedora)\n\n'
                    'or installed from source using pip e.g.\n\n'
                    '  pip install systemd-python\n\n'
                    'See here for more info: https://github.com/systemd/python-systemd/\n'
                   )

global_log = scalyr_logging.getLogger(__name__)
__monitor__ = __name__

define_config_option( __monitor__, 'journal_path',
                     'Optional (defaults to /var/log/journal). Location on disk of the journald logs.',
                     convert_to=str, default='/var/log/journal')

define_config_option( __monitor__, 'journal_poll_timeout_milliseconds',
                     'Optional (defaults to 0). The number of milliseconds to wait for data while polling the journal file. '
                     'Note: you are better off setting the sample_interval monitor option if the timeout is longer than '
                     'one second.',
                     convert_to=int, default=0)

define_config_option( __monitor__, 'journal_fields',
                     'Optional dict containing a list of journal fields to include with each message, as well as a field name to map them to.\n'
                     'Note: Not all fields need to exist in every message and only fields that exist will be included.\n'
                     'Defaults to {:\n'
                     '  "_SYSTEMD_UNIT": "unit"\n'
                     '  "_PID": "pid"\n'
                     '  "_MACHINE_ID": "machine_id"\n'
                     '  "_BOOT_ID": "boot_id"\n'
                     '  "_HOSTNAME": "hostname"\n'
                     '  "_SOURCE_REALTIME_TIMESTAMP": timestamp"\n'
                     '}\n',
                     default=None
                     )

define_config_option( __monitor__, 'journal_matches',
                      'Optional list containing match strings for filtering entries.  A match string consists of "FIELD=value" where FIELD '
                      'is a field of the journal entry e.g. _SYSTEMD_UNIT, _HOSTNAME, _GID and "value" is the value to filter on. '
                      'All matches of different field are combined with logical AND, and matches of the same field are automatically combined with logical OR. '
                      'If empty or None then no filtering occurs.',
                      default=None )

define_config_option( __monitor__, 'checkpoint_name',
                      'Optional name to use when saving the checkpoint for the journal monitor.  Defaults to the value of "journal_path". '
                      'When defining multiple monitors, define unique checkpoint_names for each monitor to ensure unqiue checkpoints are '
                      'saved for each monitor.',
                      convert_to=str, default=None )

define_config_option( __monitor__, 'staleness_threshold_secs',
                      'When loading the journal events from a checkpoint, if the logs are older than this threshold, then skip to the end.',
                      convert_to=int, default=10*60 )

class JournaldMonitor(ScalyrMonitor):

    "Read logs from journalctl and emit to scalyr"

    def _initialize(self):
        self._journal_path = self._config.get( 'journal_path' )
        if not os.path.exists( self._journal_path ):
            raise BadMonitorConfiguration( "journal_path '%s' does not exist or is not a directory" % self._journal_path )

        self._checkpoint_name = self._config.get( 'checkpoint_name' )
        if self._checkpoint_name is None:
            self._checkpoint_name = self._journal_path

        data_path = ""

        if self._global_config:
            data_path = self._global_config.agent_data_path

        self._checkpoint_file = os.path.join( data_path, "journald-checkpoints.json" )

        self._staleness_threshold_secs = self._config.get( 'staleness_threshold_secs' )

        self._journal = None
        self._poll = None
        self._poll_timeout = self._config.get( 'journal_poll_timeout_milliseconds' )
        self.log_config['parser'] = 'journald'

        self._extra_fields = self._config.get( 'journal_fields' )
        self._last_cursor = None

        matches = self._config.get( 'journal_matches' )
        if matches is None:
            matches = []

        match_re  = re.compile( "^([^=]+)=(.+)$" )
        for match in matches:
            if not match_re.match( match ):
                raise BadMonitorConfiguration( "journal matchers expects the following format for each element: FIELD=value.  Found: %s" % match, 'journal_matches' )

        self._matches = matches
        if self._extra_fields is None:
            self._extra_fields = {
                "_SYSTEMD_UNIT": "unit",
                "_PID": "pid",
                "_MACHINE_ID": "machine_id",
                "_BOOT_ID": "boot_id",
                "_HOSTNAME": "hostname",
                "_SOURCE_REALTIME_TIMESTAMP": "timestamp"
            }

    def run(self):
        self._checkpoint = journald_checkpoints.load_checkpoints( self._checkpoint_file )
        self._reset_journal()
        ScalyrMonitor.run( self )

    def _reset_journal(self):
        """
        Closes any open journal and loads the journal file located at self._journal_path
        """

        if self._journal:
            self._journal.close()

        self._journal = None
        self._poll = None

        # open the journal, limiting it to read logs since boot
        self._journal = journal.Reader(path=self._journal_path)
        self._journal.this_boot()

        # add any filters
        for match in self._matches:
            self._journal.add_match( match )

        # load the checkpoint cursor if it exists
        cursor = self._checkpoint.get_checkpoint( self._checkpoint_name )

        skip_to_end = True

        # if we have a checkpoint see if it's current
        if cursor is not None:
            try:
                self._journal.seek_cursor( cursor )
                entry = self._journal.get_next()

                timestamp = entry.get( '__REALTIME_TIMESTAMP', None )
                if timestamp:
                    current_time = datetime.datetime.utcnow()
                    delta = current_time - timestamp
                    if delta.total_seconds() < self._staleness_threshold_secs:
                        skip_to_end = False
                    else:
                        global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Checkpoint is older than %d seconds, skipping to end" % self._staleness_threshold_secs )
            except Exception, e:
                global_log.warn( "Error loading checkpoint: %s. Skipping to end." % str(e) )

        if skip_to_end:
            # seek to the end of the log
            # NOTE: we need to back up a single item, otherwise journald returns
            # random entries
            self._journal.seek_tail()
            self._journal.get_previous()

        # configure polling of the journal file
        self._poll = select.poll()
        mask = self._journal.get_events()
        self._poll.register( self._journal, mask )

    def _get_extra_fields( self, entry ):
        """
        Build a dict of key->values based on the fields available in the
        passed in journal entry, and mapped to the keys in the 'journal_fields' config option.
        """
        result = {}

        for key, value in self._extra_fields.iteritems():
            if key in entry:
                result[value] = str(entry[key])

        return result

    def _has_pending_entries(self):
        """
        Checks to see if there are any pending entries in the journal log
        that are ready for processing
        """

        # do nothing if there is nothing ready to poll
        if not self._poll.poll( self._poll_timeout ):
            return False

        # see if there are any entries to process
        process = journal.NOP
        try:
            process = self._journal.process()
        except Exception, e:
            # early return if there was an error
            global_log.warn( "Error processing journal entries: %s" % str(e),
                             limit_once_per_x_secs=60, limit_key='journald-process-error' )

            return False

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
                msg = entry.get('MESSAGE', '')
                extra = self._get_extra_fields( entry )
                self._logger.emit_value('message', msg, extra_fields=extra)
                self._last_cursor = entry.get('__CURSOR', None)
            except Exception, e:
                global_log.warn( "Error getting journal entries: %s" % str(e),
                                 limit_once_per_x_secs=60, limit_key='journald-entry-error' )

    def gather_sample(self):

        if not self._has_pending_entries():
            return

        self._process_entries()

        if self._last_cursor is not None:
            self._checkpoint.update_checkpoint( self._checkpoint_name, str( self._last_cursor ) )
