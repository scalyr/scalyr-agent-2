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

This sample will configure the agent to accept syslog messages on TCP port 601 and UDP port 514, from localhost
only:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        type:                    "Error, Warning",
      }
    ]


    """
    def _initialize( self ):
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


    def __read_from_event_log( self, source, event_log, event_types ):

        flags = win32evtlog.EVENTLOG_FORWARDS_READ|win32evtlog.EVENTLOG_SEQUENTIAL_READ

        events = True
        while events:
            events = win32evtlog.ReadEventLog( event_log, flags, 0 )
            for event in events:
                if event.EventType in event_types:
                    self.__log_event( source, event )

    def __log_event( self, source, event ):
        event_type = self.__event_types[ event.EventType ]
        data = event.StringInserts

        source = source.split( '/' )[0]

        event_message = str( win32evtlogutil.SafeFormatMessage( event, source ) )

        self._logger.emit_value( "EventLog", source, extra_fields={
            'Source': event.SourceName,
            'RecordNumber': event.RecordNumber,
            'Type' : event_type,
            'EventId': event.EventID,
            'Category': event.EventCategory,
            'Message' : event_message,
        } )

    def run( self ):
        for source in self.__source_list:
            event_log = win32evtlog.OpenEventLog( self.__server, source )
            if event_log:
                self.__event_logs[source] = event_log

        ScalyrMonitor.run( self )

    def gather_sample( self ):
        for source, event_log in self.__event_logs.iteritems():
            self.__read_from_event_log( source, event_log, self.__event_types )



