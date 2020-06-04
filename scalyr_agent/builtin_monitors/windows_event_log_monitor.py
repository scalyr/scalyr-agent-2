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
# author:  Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

import os
import threading
import time

import six

try:
    import win32api
    import win32evtlog
    import win32evtlogutil
    import win32con
    from ctypes import windll  # type: ignore
except ImportError:
    win32evtlog = None
    win32evtlogutil = None
    win32con = None
    windll = None

import scalyr_agent.util as scalyr_util
from scalyr_agent import ScalyrMonitor, define_config_option
import scalyr_agent.scalyr_logging as scalyr_logging

__author__ = "imron@scalyr.com"

__monitor__ = __name__

DEFAULT_SOURCES = "Application, Security, System"
DEFAULT_EVENTS = "All"

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.windows_event_log_monitor``",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "sources",
    "Optional (defaults to ``Application, Security, System``). A comma separated list of event sources.\n"
    "You can use this to specify which event sources you are interested in listening to."
    '(Vista and later) Cannot be used.  Please use the "channels" parameter instead.',
    convert_to=six.text_type,
    default=DEFAULT_SOURCES,
)

define_config_option(
    __monitor__,
    "event_types",
    "Optional (defaults to ``All``). A comma separated list of event types to log.\n"
    "Valid values are: All, Error, Warning, Information, AuditSuccess and AuditFailure"
    '(Vista and later) Cannot be used.  Please use the "channels" parameter instead.',
    default=DEFAULT_EVENTS,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "channels",
    "A list of dict objects specifying a list of channels and an XPath query for those channels.\n"
    "Only available on Windows Vista and later.\n"
    'Optional (defaults to ``[ {"channel" : ["Application", "Security", "System"], "query": "*"}]\n',
    convert_to=None,
)

define_config_option(
    __monitor__,
    "maximum_records_per_source",
    "Optional (defaults to ``10000``). The maximum number of records to read from the end of each log source"
    "per gather_sample.\n",
    default="10000",
    convert_to=int,
)

define_config_option(
    __monitor__,
    "error_repeat_interval",
    "Optional (defaults to ``300``). The number of seconds to wait before logging similar errors in the event log.\n",
    default="300",
    convert_to=int,
)

define_config_option(
    __monitor__,
    "server_name",
    "Optional (defaults to ``localhost``). The remote server where the event log is to be opened\n",
    default="localhost",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_user",
    "Optional (defaults to ``None``). The username to use for authentication on the remote server.  This option is only valid on Windows Vista and above\n",
    default=None,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_password",
    "Optional (defaults to ``None``). The password to use for authentication on the remote server.  This option is only valid on Windows Vista and above\n",
    default=None,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_domain",
    "Optional (defaults to ``None``). The domain to which the remote user account belongs.  This option is only valid on Windows Vista and above\n",
    default=None,
    convert_to=six.text_type,
)


class Api(object):
    def __init__(self, config, logger):
        self._checkpoints = {}
        self._logger = logger
        self._server = config.get("server_name")

        self._error_repeat_interval = config.get("error_repeat_interval")
        self._maximum_records = config.get("maximum_records_per_source")

    @property
    def checkpoints(self):
        return self._checkpoints

    def load_checkpoints(self, checkpoints, config):
        pass

    def update_checkpoints(self):
        pass

    def read_event_log(self):
        pass

    def stop(self):
        pass


class OldApi(Api):
    def __init__(self, config, logger, source_list, event_filter):
        super(OldApi, self).__init__(config, logger)

        self.__log_critical = False
        self.__event_types = {}

        for event in event_filter:
            if event == "Error":
                self.__event_types[win32con.EVENTLOG_ERROR_TYPE] = event
            elif event == "Warning":
                self.__event_types[win32con.EVENTLOG_WARNING_TYPE] = event
            elif event == "Information":
                self.__event_types[win32con.EVENTLOG_INFORMATION_TYPE] = event
            elif event == "AuditSuccess":
                self.__event_types[win32con.EVENTLOG_AUDIT_SUCCESS] = event
            elif event == "AuditFailure":
                self.__event_types[win32con.EVENTLOG_AUDIT_FAILURE] = event
            elif event == "Critical":
                # The OldApi can't read critical events so set a flag to warn the user
                self.__log_critical = True

        self.__sources = source_list

    def load_checkpoints(self, checkpoints, config):
        for source, record_number in six.iteritems(checkpoints):
            self._checkpoints[source] = record_number

    def read_event_log(self):
        if self.__log_critical:
            self._logger.warn(
                "Critical events specified in config, but these events cannot be retrieved on Windows versions prior to Vista.",
                limit_once_per_x_secs=self._error_repeat_interval,
                limit_key="EventLogCriticalEvents",
            )

        for source in self.__sources:
            self.__read_from_event_log(source, self.__event_types)

    def __read_from_event_log(self, source, event_types):

        event_log = win32evtlog.OpenEventLog(self._server, source)
        if not event_log:
            self._logger.error("Unknown error opening event log for '%s'" % source)
            return

        # we read events in reverse from the end of the log to avoid problems when
        # seeking directly to a record in a large log file
        flags = (
            win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        )

        offset = -1

        # use the checkpoint if it exists
        if source in self._checkpoints:
            offset = self._checkpoints[source]

        # a list of events that we haven't yet seen
        event_list = []
        try:
            events = True
            while events:
                events = win32evtlog.ReadEventLog(event_log, flags, offset)
                for event in events:
                    # special case for when there was no offset, in which case
                    # the first event will be the latest event so use that for the
                    # new offset
                    if offset == -1:
                        self._checkpoints[source] = event.RecordNumber
                        events = False
                        break
                    # if we encounter our last seen record, then we are done
                    elif (
                        offset == event.RecordNumber
                        or len(event_list) >= self._maximum_records
                    ):
                        events = False
                        break
                    else:
                        # add the event to our list of interested events
                        # if it is one we are interested in
                        if event.EventType in event_types:
                            event_list.append(event)
        except Exception as error:
            self._logger.error(
                "Error reading from event log: %s",
                six.text_type(error),
                limit_once_per_x_secs=self._error_repeat_interval,
                limit_key="EventLogError",
            )

        # now print out records in reverse order (which will put them in correct chronological order
        # because we initially read them in reverse)
        for event in reversed(event_list):
            self.__log_event(source, event)
            self._checkpoints[source] = event.RecordNumber

    def __log_event(self, source, event):
        """ Emits information about an event to the logfile for this monintor
        """
        event_type = self.__event_types[event.EventType]

        # we need to get the root source e.g. Application in Application/MyApplication
        # to use with SafeFormatMessage
        source = source.split("/")[0]
        event_message = win32evtlogutil.SafeFormatMessage(event, source)
        time_format = "%Y-%m-%d %H:%M:%SZ"

        self._logger.emit_value(
            "EventLog",
            source,
            extra_fields={
                "Source": event.SourceName,
                "RecordNumber": event.RecordNumber,
                "TimeGenerated": time.strftime(
                    time_format, time.gmtime(int(event.TimeGenerated))
                ),
                "TimeWritten": time.strftime(
                    time_format, time.gmtime(int(event.TimeWritten))
                ),
                "Type": event_type,
                "EventId": event.EventID,
                "Category": event.EventCategory,
                "EventMsg": event_message,
            },
        )


def event_callback(reason, context, event):
    context.log_event_safe(event)


class NewApi(Api):
    def __init__(self, config, logger, channels):
        super(NewApi, self).__init__(config, logger)
        self.__eventHandles = []
        if not channels:
            channels = [
                {"channel": ["Application", "System", "Security"], "query": "*"}
            ]

        self.__bookmark_lock = threading.Lock()
        self.__channels = channels
        self.__channel_list = []
        self._session = None
        seen = {}
        # build a list of unique channels
        for info in channels:
            current_channels = info["channel"]
            for channel in current_channels:
                if channel not in seen:
                    seen[channel] = 1
                    self.__channel_list.append(channel)

        self.__bookmarks = {}

    def _open_remote_session_if_necessary(self, server, config):
        """
            Opens a session to a remote server if `server` is not localhost or None
            @param server: string containing the server to connect to (can be None)
            @param config: a log config object
            @return: a valid session to a remote machine, or None if no remote session was needed
        """
        session = None

        # see if we need to create a remote connection
        if server is not None and server != "localhost":
            username = config.get("remote_user")
            password = config.get("remote_password")
            domain = config.get("remote_domain")
            flags = win32evtlog.EvtRpcLoginAuthDefault

            # login object is a tuple
            login = (server, username, domain, password, flags)
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Performing remote login: server - %s, user - %s, domain - %s"
                % (server, username, domain),
            )

            session = None
            session = win32evtlog.EvtOpenSession(login, win32evtlog.EvtRpcLogin, 0, 0)

            if session is None:
                # 0 means to call GetLastError for the error code
                error_message = win32api.FormatMessage(0)
                self._logger.warn(
                    "Error connecting to remote server %s, as %s - %s"
                    % (server, username, error_message)
                )
                raise Exception(
                    "Error connecting to remote server %s, as %s - %s"
                    % (server, username, error_message)
                )

        return session

    def _subscribe_to_events(self):
        """
            Go through all channels, and create an event subscription to that channel.
            If a bookmark exists for a given channel, start the events from that bookmark, otherwise subscribe
            to future events only.
        """

        for info in self.__channels:
            channel_list = info["channel"]
            query = info["query"]
            for channel in channel_list:
                self._logger.info("subscribing to %s, %s", channel, query)
                # subscribe to future events
                flags = win32evtlog.EvtSubscribeToFutureEvents
                bookmark = None
                try:
                    # unless we have a bookmark for this channel
                    self.__bookmark_lock.acquire()
                    if channel in self.__bookmarks:
                        flags = win32evtlog.EvtSubscribeStartAfterBookmark
                        bookmark = self.__bookmarks[channel]
                finally:
                    self.__bookmark_lock.release()

                error_message = None
                try:
                    handle = win32evtlog.EvtSubscribe(
                        channel,
                        flags,
                        Bookmark=bookmark,
                        Query=query,
                        Callback=event_callback,
                        Context=self,
                        Session=self._session,
                    )
                except Exception:
                    handle = None
                    error_message = win32api.FormatMessage(0)

                if handle is None:
                    self._logger.warn(
                        "Error subscribing to channel '%s' - %s"
                        % (channel, error_message)
                    )
                else:
                    self.__eventHandles.append(handle)

    def load_checkpoints(self, checkpoints, config):

        # open a remote session if needed - we do this before creating the bookmarks and event subscriptions,
        # because this method could fail with an Exception, so check to see if we can actually connect before
        # doing any further work.
        # Assign the result to a member variable so that the session remains open for the lifetime of the object
        self._session = self._open_remote_session_if_necessary(self._server, config)

        # only use new checkpoints
        if "api" not in checkpoints or checkpoints["api"] != "new":
            checkpoints = {}

        self._checkpoints["api"] = "new"
        self._checkpoints["bookmarks"] = {}
        if "bookmarks" not in checkpoints:
            checkpoints["bookmarks"] = {}

        for channel, bookmarkXml in six.iteritems(checkpoints["bookmarks"]):
            self.__bookmarks[channel] = win32evtlog.EvtCreateBookmark(bookmarkXml)

        # subscribe to the events
        self._subscribe_to_events()

        # make sure we have at least one successfully subscribed channel
        if len(self.__eventHandles) == 0:
            raise Exception("Failed to subscribe to any channels")

    def update_checkpoints(self):
        self._checkpoints["api"] = "new"

        self.__bookmark_lock.acquire()
        try:
            for channel, bookmark in six.iteritems(self.__bookmarks):
                self._checkpoints["bookmarks"][channel] = win32evtlog.EvtRender(
                    bookmark, win32evtlog.EvtRenderBookmark
                )
        finally:
            self.__bookmark_lock.release()

    def stop(self):
        # explicitly empty the eventHandles array so that EvtClose will be called
        # on all the event handles - this prevents duplicate logs if the config changes
        self.__eventHandles = []

    def _FormattedMessage(self, metadata, event, field, value):
        result = value
        try:
            result = win32evtlog.EvtFormatMessage(metadata, event, field)
        except Exception:
            pass

        return result

    def _AddValueIfNotNullType(self, items, key, value):
        if value[1] != win32evtlog.EvtVarTypeNull:
            items[key] = value[0]

    def GetFormattedEventAsDict(self, render_context, event):
        vals = win32evtlog.EvtRender(
            event, win32evtlog.EvtRenderEventValues, Context=render_context
        )

        result = {}

        # In the new event log api, EventIds were replaced by an InstanceId.
        # The InstanceID is made by combining the old EventId with any
        # SystemQualifiers associated with the event, to create a new 32bit value
        # with the EventId in the lower 16bits and the SystemQualifiers
        # in the high 16bits.
        event_id_val = vals[win32evtlog.EvtSystemEventID]
        if event_id_val[1] != win32evtlog.EvtVarTypeNull:
            # by default use the event id value as the event id
            event_id = event_id_val[0]
            qualifiers_val = vals[win32evtlog.EvtSystemQualifiers]
            # if we have any system qualifiers for this event
            if qualifiers_val[1] != win32evtlog.EvtVarTypeNull:
                # then combine the event id with the qualifiers to
                # make the full event id.
                event_id = win32api.MAKELONG(event_id, qualifiers_val[0])
            result["EventID"] = event_id

        metadata = None
        try:
            metadata = win32evtlog.EvtOpenPublisherMetadata(
                vals[win32evtlog.EvtSystemProviderName][0]
            )
        except Exception:
            pass

        result["Message"] = self._FormattedMessage(
            metadata, event, win32evtlog.EvtFormatMessageEvent, ""
        )

        if vals[win32evtlog.EvtSystemLevel][1] != win32evtlog.EvtVarTypeNull:
            result["Level"] = self._FormattedMessage(
                metadata,
                event,
                win32evtlog.EvtFormatMessageLevel,
                vals[win32evtlog.EvtSystemLevel][0],
            )

        if vals[win32evtlog.EvtSystemOpcode][1] != win32evtlog.EvtVarTypeNull:
            result["Opcode"] = self._FormattedMessage(
                metadata,
                event,
                win32evtlog.EvtFormatMessageOpcode,
                vals[win32evtlog.EvtSystemOpcode][0],
            )

        if vals[win32evtlog.EvtSystemKeywords][1] != win32evtlog.EvtVarTypeNull:
            result["Keywords"] = self._FormattedMessage(
                metadata,
                event,
                win32evtlog.EvtFormatMessageKeyword,
                vals[win32evtlog.EvtSystemKeywords][0],
            )

        if vals[win32evtlog.EvtSystemChannel][1] != win32evtlog.EvtVarTypeNull:
            result["Channel"] = self._FormattedMessage(
                metadata,
                event,
                win32evtlog.EvtFormatMessageChannel,
                vals[win32evtlog.EvtSystemChannel][0],
            )
        result["Task"] = self._FormattedMessage(
            metadata, event, win32evtlog.EvtFormatMessageTask, ""
        )

        self._AddValueIfNotNullType(
            result, "ProviderName", vals[win32evtlog.EvtSystemProviderName]
        )
        self._AddValueIfNotNullType(
            result, "ProviderGuid", vals[win32evtlog.EvtSystemProviderGuid]
        )
        self._AddValueIfNotNullType(
            result, "TimeCreated", vals[win32evtlog.EvtSystemTimeCreated]
        )
        self._AddValueIfNotNullType(
            result, "RecordId", vals[win32evtlog.EvtSystemEventRecordId]
        )
        self._AddValueIfNotNullType(
            result, "ActivityId", vals[win32evtlog.EvtSystemActivityID]
        )
        self._AddValueIfNotNullType(
            result, "RelatedActivityId", vals[win32evtlog.EvtSystemRelatedActivityID]
        )
        self._AddValueIfNotNullType(
            result, "ProcessId", vals[win32evtlog.EvtSystemProcessID]
        )
        self._AddValueIfNotNullType(
            result, "ThreadId", vals[win32evtlog.EvtSystemThreadID]
        )
        self._AddValueIfNotNullType(
            result, "Computer", vals[win32evtlog.EvtSystemComputer]
        )
        self._AddValueIfNotNullType(result, "UserId", vals[win32evtlog.EvtSystemUserID])
        self._AddValueIfNotNullType(
            result, "Version", vals[win32evtlog.EvtSystemVersion]
        )

        return result

    def log_event_safe(self, event):
        try:
            self.log_event(event)
        except Exception as e:
            try:
                self._logger.info("%s", six.text_type(e))
            except Exception:
                self._logger.info("Error printing exception information")

    def log_event(self, event):
        render_context = win32evtlog.EvtCreateRenderContext(
            win32evtlog.EvtRenderContextSystem
        )
        vals = self.GetFormattedEventAsDict(render_context, event)
        provider = "not-specified"
        if "ProviderName" in vals:
            provider = vals["ProviderName"]

        if "ProviderGuid" in vals:
            vals["ProviderGuid"] = six.text_type(vals["ProviderGuid"])

        if "ActivityId" in vals:
            vals["ActivityId"] = six.text_type(vals["ActivityId"])

        if "RelatedActivityId" in vals:
            vals["RelatedActivityId"] = six.text_type(vals["RelatedActivityId"])

        if "TimeCreated" in vals:
            time_format = "%Y-%m-%d %H:%M:%SZ"
            vals["TimeCreated"] = time.strftime(
                time_format, time.gmtime(int(vals["TimeCreated"]))
            )

        if "Keywords" in vals:
            if isinstance(vals["Keywords"], list):
                vals["Keywords"] = ",".join(vals["Keywords"])
            else:
                vals["Keywords"] = six.text_type(vals["Keywords"])

        if "UserId" in vals:
            user_id = six.text_type(vals["UserId"])
            if user_id.startswith("PySID:"):
                user_id = user_id[6:]
            vals["UserId"] = user_id

        self._logger.emit_value("EventLog", provider, extra_fields=vals)

        self.__bookmark_lock.acquire()
        try:
            if "Channel" in vals:
                channel = vals["Channel"]
                bookmark = None
                if channel not in self.__bookmarks:
                    self.__bookmarks[channel] = win32evtlog.EvtCreateBookmark(None)

                bookmark = self.__bookmarks[channel]
                win32evtlog.EvtUpdateBookmark(bookmark, event)
        finally:
            self.__bookmark_lock.release()


class WindowEventLogMonitor(ScalyrMonitor):
    """
# Window Event Log Monitor

The Windows Event Log monitor uploads messages from the Windows Event Log to the Scalyr servers.
It can listen to multiple different event sources and also filter by messages of a certain type.

On versions of Windows prior to Vista, the older EventLog API is used.  This API is unable to
retrieve 'Critical' events because this event type was only introduced in Vista.

On versions of Windows from Vista onwards, the newer Evt API is used which can be used to retrieve
'Critical' events.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

### Windows Vista and later

On Windows Vista and later, the Scalyr agent uses the EvtLog API, and you can configure it to query events on any channel, using the standard XPath query mechanism.  See: https://msdn.microsoft.com/en-us/library/windows/desktop/dd996910(v=vs.85).aspx

For example, the following will configure the agent to listen to Critical, Error and Warning level events from the Application, Security and System channels:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]

Alternatively, here is a configuration that will log critical errors for the Application channel, and critical, error and warning messages for System and Security channels.

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Application"],
              "query": "*[System/Level=1]"
            },
            {
              "channel": ["Security", "System" ],
              "query": "*[System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]

### Windows Server 2003

For Windows versions earlier than Vista, the Scalyr agent will use the older Event Log API.

This sample will configure the agent running on Windows Server 2003 to listen to Error and Warning level events from the Application, Security
and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        event_types:             "Error, Warning",
      }
    ]
    """

    def _initialize(self):
        # get the checkpoint file
        data_path = ""
        if self._global_config:
            data_path = self._global_config.agent_data_path
        self.__checkpoint_file = os.path.join(
            data_path, "windows-event-checkpoints.json"
        )

        sources = self._config.get("sources")
        event_types = self._config.get("event_types")
        channels = self._config.get("channels")

        self.__api = self.__get_api(sources, event_types, channels)

    def __load_checkpoints(self):

        checkpoints = None
        try:
            checkpoints = scalyr_util.read_file_as_json(
                self.__checkpoint_file, strict_utf8=True
            )
        except Exception:
            self._logger.info(
                "No checkpoint file '%s' exists.\nAll logs will be read starting from their current end.",
                self.__checkpoint_file,
            )
            checkpoints = {}

        self.__api.load_checkpoints(checkpoints, self._config)

    def __update_checkpoints(self):
        # updatedate the api's checkpoints
        self.__api.update_checkpoints()

        # save to disk
        if self.__api.checkpoints:
            tmp_file = self.__checkpoint_file + "~"
            scalyr_util.atomic_write_dict_as_json_file(
                self.__checkpoint_file, tmp_file, self.__api.checkpoints
            )

    def __get_api(self, sources, events, channels):
        evtapi = False
        if windll:
            try:
                if windll.wevtapi:
                    evtapi = True
            except Exception:
                pass

        result = None

        # convert sources into a list
        source_list = [s.strip() for s in sources.split(",")]

        # convert event types in to a list
        event_filter = [s.strip() for s in events.split(",")]

        # build the event filter
        if "All" in event_filter:
            event_filter = [
                "Error",
                "Warning",
                "Information",
                "AuditSuccess",
                "AuditFailure",
            ]

        if evtapi:
            if sources != DEFAULT_SOURCES or events != DEFAULT_EVENTS:
                raise Exception(
                    "Sources and Events not supported with the new EvtLog API.  Please use the 'channels' configuration option instead"
                )

            result = NewApi(self._config, self._logger, channels)
        else:
            if channels:
                raise Exception(
                    "Channels are not supported on the older Win32 EventLog API"
                )

            result = OldApi(self._config, self._logger, source_list, event_filter)

        return result

    def run(self):
        self.__load_checkpoints()
        if isinstance(self.__api, NewApi):
            self._logger.info("Using new Evt API")
        if isinstance(self.__api, OldApi):
            self._logger.info("Evt API not detected.  Using older EventLog API")

        ScalyrMonitor.run(self)

    def stop(self, wait_on_join=True, join_timeout=5):
        # stop the monitor
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)

        # stop any event monitoring
        self.__api.stop()

        # update checkpoints
        self.__update_checkpoints()

    def gather_sample(self):

        self.__api.read_event_log()

        self.__update_checkpoints()
