# Copyright 2105 Scalyr Inc.
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
# author:  Imron Alston <imron@imralsoftware.com>

import datetime
import os
import scalyr_agent.util as scalyr_util
import time
import win32evtlog
import win32evtlogutil
import win32con

from scalyr_agent import ScalyrMonitor, define_config_option

__author__ = 'imron@imralsoftware.com'

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.windows_event_log_monitor``',
                     convert_to=str, required_option=True)
define_config_option( __monitor__, 'sources',
                     'Optional (defaults to ``Application, Security, System``). A comma separated list of event sources.\n'
                     'You can use this to specify which event sources you are interested in listening to.',
                     convert_to=str, default='Application, Security, System')

define_config_option(__monitor__, 'event_types',
                     'Optional (defaults to ``All``). A comma separated list of event types to log.\n'
                     'Valid values are: All, Error, Warning, Information, AuditSuccess and AuditFailure',
                     default='All', convert_to=str)

define_config_option(__monitor__, 'error_repeat_interval',
                     'Optional (defaults to ``300``). The number of seconds to wait before logging similar errors in the event log.\n',
                     default='300', convert_to=int)

define_config_option(__monitor__, 'server_name',
                     'Optional (defaults to ``localhost``). The remote server where the event log is to be opened\n',
                     default='localhost', convert_to=str)

class WindowEventLogMonitor( ScalyrMonitor ):
    """
# Window Event Log Monitor

The Windows Event Log monitor upload messages from the windows event log to the Scalyr servers.
It can listen to multiple different event sources, and also filter by messages of a certain type.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

This sample will configure the agent to listen to Error and Warning level events from the Application, Security
and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        type:                    "Error, Warning",
      }
    ]


    """
    def _initialize( self ):
        #get the checkpoint file
        data_path = ""
        if self._global_config:
            data_path = self._global_config.agent_data_path
        self.__checkpoint_file = os.path.join( data_path, "windows-event-checkpoints.json" )
        self.__checkpoints = {}

        #convert sources into a list
        sources = self._config.get( 'sources' )
        self.__source_list = [s.strip() for s in sources.split(',')]
        self.__event_logs = {}

        #convert event types in to a list
        event_types = self._config.get( 'event_types' )
        event_filter = [s.strip() for s in event_types.split(',')]

        # build the event filter
        self.__event_types = {}
        if 'All' in event_filter:
            event_filter = [ 'Error', 'Warning', 'Information', 'AuditSuccess', 'AuditFailure' ]

        for event in event_filter:
            if event == 'Error':
                self.__event_types[ win32con.EVENTLOG_ERROR_TYPE ] = event
            elif event == 'Warning':
                self.__event_types[ win32con.EVENTLOG_WARNING_TYPE ] = event
            elif event == 'Information':
                self.__event_types[ win32con.EVENTLOG_INFORMATION_TYPE ] = event
            elif event == 'AuditSuccess':
                self.__event_types[ win32con.EVENTLOG_AUDIT_SUCCESS ] = event
            elif event == 'AuditFailure':
                self.__event_types[ win32con.EVENTLOG_AUDIT_FAILURE ] = event

        self.__server = self._config.get( 'localhost' )

        self.__error_repeat_interval = self._config.get( 'error_repeat_interval' )


    def __load_checkpoints( self ):

        checkpoints = None
        try:
            checkpoints = scalyr_util.read_file_as_json( self.__checkpoint_file )
        except:
            self._logger.info( "Error reading checkpoint file '%s'.\n\tAll logs will be read starting from their current end.", self.__checkpoint_file )
            checkpoints = {}

        if checkpoints:
            for source, record_number in checkpoints.iteritems():
                self.__checkpoints[source] = record_number

    def __update_checkpoints( self ):
        # save to disk
        if self.__checkpoints:
            tmp_file = self.__checkpoint_file + '~'
            scalyr_util.atomic_write_dict_as_json_file( self.__checkpoint_file, tmp_file, self.__checkpoints )

    def __read_from_event_log( self, source, event_log, event_types ):

        flags = win32evtlog.EVENTLOG_FORWARDS_READ|win32evtlog.EVENTLOG_SEEK_READ

        offset = 0

        #use the checkpoint
        if source in self.__checkpoints:
            offset = self.__checkpoints[source]
        else:
            # or the most recent log if there was no checkpoint for this source
            offset = win32evtlog.GetNumberOfEventLogRecords( event_log )

        try:
            events = True
            while events:
                    events = win32evtlog.ReadEventLog( event_log, flags, offset )
                    for event in events:
                        # ignore the record if it's same as the offset (because we seek to the
                        # last record we have seen)
                        # and also if it is not an event type we are interested in
                        if offset != event.RecordNumber and event.EventType in event_types:
                            self.__log_event( source, event )
                        self.__checkpoints[source] = event.RecordNumber
                    offset = 0
                    flags = win32evtlog.EVENTLOG_FORWARDS_READ|win32evtlog.EVENTLOG_SEQUENTIAL_READ
        except Exception, error:
            self._logger.error( "Error reading from event log: %s", str( error ), limit_once_per_x_secs=self.__error_repeat_interval, limit_key="EventLogError" )


    def __log_event( self, source, event ):
        """ Emits information about an event to the logfile for this monintor
        """
        event_type = self.__event_types[ event.EventType ]

        # we need to get the root source e.g. Application in Application/MyApplication
        # to use with SafeFormatMessage
        source = source.split( '/' )[0]
        event_message = str( win32evtlogutil.SafeFormatMessage( event, source ) )
        time_format = "%Y-%m-%d %H:%M:%SZ"

        self._logger.emit_value( "EventLog", source, extra_fields={
            'Source': event.SourceName,
            'RecordNumber': event.RecordNumber,
            'TimeGenerated': time.strftime( time_format, time.gmtime(int( event.TimeGenerated ))),
            'TimeWritten': time.strftime( time_format, time.gmtime(int( event.TimeWritten ))),
            'Type' : event_type,
            'EventId': event.EventID,
            'Category': event.EventCategory,
            'Message' : event_message,
        } )

    def __open_event_logs( self ):
        for source in self.__source_list:
            event_log = win32evtlog.OpenEventLog( self.__server, source )
            if event_log:
                self.__event_logs[source] = event_log

    def run( self ):
        self.__load_checkpoints()
        self.__open_event_logs()

        ScalyrMonitor.run( self )

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the monitor
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

        #update checkpoints
        self.__update_checkpoints()

    def gather_sample( self ):
        for source, event_log in self.__event_logs.iteritems():
            self.__read_from_event_log( source, event_log, self.__event_types )

        self.__update_checkpoints()


