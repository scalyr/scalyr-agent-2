# Copyright 2011-2022 Scalyr Inc.
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
# author: scalyr-cloudtech@scalyr.com

from __future__ import unicode_literals
from __future__ import absolute_import

import copy
import collections
import os
import re
import threading
import time

import six
import xmltodict

try:
    import win32api
    import win32evtlog
    import win32evtlogutil
    import win32con
    from ctypes import windll  # type: ignore

    WIN32_IMPORT_ERROR = ""
except ImportError as e:
    WIN32_IMPORT_ERROR = str(e)

    win32evtlog = None
    win32evtlogutil = None
    win32con = None
    windll = None

import scalyr_agent.util as scalyr_util
from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field
import scalyr_agent.scalyr_logging as scalyr_logging

__author__ = "scalyr-cloudtech@scalyr.com"

__monitor__ = __name__

DEFAULT_SOURCES = "Application, Security, System"
DEFAULT_EVENTS = "All"

DEFAULT_MAXIMUM_RECORDS_PER_SOURCE = 10000

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.windows_event_log_monitor`",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "sources",
    "Optional (defaults to `Application, Security, System`). A comma separated list "
    "of sources to import events from. (Not valid for Vista and later; use `channels` "
    "instead.)",
    convert_to=six.text_type,
    default=DEFAULT_SOURCES,
)

define_config_option(
    __monitor__,
    "event_types",
    "Optional (defaults to `All`). A comma separated list of event types to import. "
    "Valid values are: `All`, `Error`, `Warning`, `Information`, `AuditSuccess`, and "
    "`AuditFailure`. (Not valid for Vista and later; use `channels` instead.)",
    default=DEFAULT_EVENTS,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "channels",
    'Optional (defaults to `[{"channel" : ["Application", "Security", "System"], "query": "*"}]`). '
    "A list of dict objects specifying a list of channels, and an XPath query for those channels. "
    "(Only available on Windows Vista and later.)",
    convert_to=None,
)

define_config_option(
    __monitor__,
    "maximum_records_per_source",
    "Optional (defaults to `10000`). Maximum number of records to read from the end of each "
    "log source per gather_sample.",
    convert_to=int,
)

define_config_option(
    __monitor__,
    "error_repeat_interval",
    "Optional (defaults to `300`). Number of seconds to wait before logging similar errors in the event log.",
    default="300",
    convert_to=int,
)

define_config_option(
    __monitor__,
    "server_name",
    "Optional (defaults to `localhost`). The remote server to import events from.",
    default="localhost",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_user",
    "Optional (defaults to `none`). Username for authentication on the remote server. "
    "This option is only valid on Windows Vista and above.",
    default=None,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_password",
    "Optional (defaults to `none`). Password to use for authentication on the remote server.  "
    "This option is only valid on Windows Vista and above.",
    default=None,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "remote_domain",
    "Optional (defaults to `none`). The domain for the remote user account. "
    "This option is only valid on Windows Vista and above.",
    default=None,
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "json",
    "Optional (defaults to `false`). Format events as json? Supports inclusion of "
    "all event fields. This option is only valid on Windows Vista and above.",
    default=False,
    convert_to=bool,
)

define_config_option(
    __monitor__,
    "placeholder_render",
    "Optional (defaults to `false`). Render %%n placeholders in event data? This option is only "
    "valid on Windows Vista and above.",
    default=False,
    convert_to=bool,
)

define_config_option(
    __monitor__,
    "dll_handle_cache_size",
    "Optional (defaults to `10`). DLL handle cache size, applicable only if `placeholder_render` "
    "is set. This option is only valid on Windows Vista and above.",
    default=10,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "placeholder_param_cache_size",
    "Optional (defaults to `1000`). Placeholder parameter cache size, applicable only if "
    "`placeholder_render` is set. This option is only valid on Windows Vista and above.",
    default=1000,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "dll_handle_cache_ttl",
    "Optional (defaults to `86400` ie 24 hours). DLL handle cache TTL, applicable only if "
    "`placeholder_render` is set. This option is only valid on Windows Vista and above.",
    default=86400,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "placeholder_param_cache_ttl",
    "Optional (defaults to `86400` ie 24 hours). Placeholder parameter cache TLL, applicable only "
    "if `placeholder_render` is set. This option is only valid on Windows Vista and above.",
    default=86400,
    convert_to=int,
)

define_log_field(__monitor__, "monitor", "Always ``windows_event_log_monitor``.")


define_log_field(
    __monitor__,
    "monitor",
    "Always `windows_event_log_monitor`.",
)
define_log_field(
    __monitor__,
    "Channel",
    "The event channel name, taken from the `Event.System.Channel` field. "
    "Only for Vista and above; see `Source` for pre-Vista versions.",
)
define_log_field(
    __monitor__,
    "EventRecordID",
    "The event record number, taken from the `Event.System.EventRecordID` field. "
    "Only for Vista and above; see `RecordNumber` for pre-Vista versions.",
)
define_log_field(
    __monitor__,
    "SystemTime",
    "The time the event was generated, taken from the `Event.System.TimeCreated.SystemTime` "
    "field. Only for Vista and above; see `RecordNumber` for pre-Vista versions.",
)
define_log_field(
    __monitor__,
    "EventId",
    "The event id, taken from the `Event.System.EventID` field on Vista and above, "
    "and from `event.EventID` for pre-Vista versions.",
)
define_log_field(
    __monitor__,
    "Source",
    "The event source name, taken from the `event.SourceName` field. "
    "Only for pre-Vista versions of Windows; see `Channel` for Vista and above.",
)
define_log_field(
    __monitor__,
    "RecordNumber",
    "The event record number, taken from the `event.RecordNumber` field. "
    "Only for pre-Vista versions of Windows; see `SystemTime` for Vista and above.",
)
define_log_field(
    __monitor__,
    "TimeGenerated",
    "The time the event was generated. "
    "Only for pre-Vista versions of Windows; see `SystemTime` for Vista and above.",
)
define_log_field(
    __monitor__,
    "Type",
    "The event type. Only for pre-Vista versions of Windows.",
)
define_log_field(
    __monitor__,
    "Category",
    "The event category, taken from the `event.EventCategory` field. "
    "Only for pre-Vista versions of Windows.",
)
define_log_field(
    __monitor__,
    "EventMsg",
    "The contents of the event message from the Windows Event Log. "
    "Only for pre-Vista versions of Windows.",
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
        """Emits information about an event to the logfile for this monintor"""
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

        self._bookmarks = {}
        self._bookmark_lock = threading.Lock()

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
                    self._bookmark_lock.acquire()
                    if channel in self._bookmarks:
                        flags = win32evtlog.EvtSubscribeStartAfterBookmark
                        bookmark = self._bookmarks[channel]
                finally:
                    self._bookmark_lock.release()

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
            self._bookmarks[channel] = win32evtlog.EvtCreateBookmark(bookmarkXml)

        # subscribe to the events
        self._subscribe_to_events()

        # make sure we have at least one successfully subscribed channel
        if len(self.__eventHandles) == 0:
            raise Exception("Failed to subscribe to any channels")

    def update_checkpoints(self):
        self._checkpoints["api"] = "new"

        self._bookmark_lock.acquire()
        try:
            for channel, bookmark in six.iteritems(self._bookmarks):
                self._checkpoints["bookmarks"][channel] = win32evtlog.EvtRender(
                    bookmark, win32evtlog.EvtRenderBookmark
                )
        finally:
            self._bookmark_lock.release()

    def stop(self):
        """
        Close all handles for event subscriptions.
        """
        for handle in self.__eventHandles:
            res = windll.wevtapi.EvtClose(handle.handle)
            if not res:
                self._logger.error(
                    "Can not close event subscription handle '{0}'.".format(
                        handle.handle
                    )
                )
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
            vals["TimeCreated"] = vals["TimeCreated"].strftime(time_format)

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

        self._bookmark_lock.acquire()
        try:
            if "Channel" in vals:
                channel = vals["Channel"]
                if channel not in self._bookmarks:
                    self._bookmarks[channel] = win32evtlog.EvtCreateBookmark(None)
                win32evtlog.EvtUpdateBookmark(self._bookmarks[channel], event)
        finally:
            self._bookmark_lock.release()


class NewJsonApi(NewApi):
    def __init__(self, config, logger, channels):
        super(NewJsonApi, self).__init__(config, logger, channels)

        self._render_context = win32evtlog.EvtCreateRenderContext(
            win32evtlog.EvtRenderContextSystem
        )

        self._placeholder_render = config.get("placeholder_render")
        if self._placeholder_render:
            self._dll_cache = Cache(
                size=config.get("dll_handle_cache_size"),
                ttl=config.get("dll_handle_cache_ttl"),
            )
            self._param_cache = Cache(
                size=config.get("placeholder_param_cache_size"),
                ttl=config.get("placeholder_param_cache_ttl"),
            )

            self._cache_report_interval = 3600 * 12
            self._next_cache_report = time.time() + self._cache_report_interval

            self._langid = win32api.MAKELANGID(
                win32con.LANG_NEUTRAL, win32con.SUBLANG_NEUTRAL
            )

    def log_event(self, event):
        values = win32evtlog.EvtRender(
            event, win32evtlog.EvtRenderEventValues, Context=self._render_context
        )

        # (Publisher) metadata is used to populate the RenderingInfo section,
        # which is already populated for forwarded events and would throw an exception here.
        # Ref: https://docs.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtformatmessage
        metadata = None
        try:
            metadata = win32evtlog.EvtOpenPublisherMetadata(
                values[win32evtlog.EvtSystemProviderName][0]
            )
        except Exception:
            pass

        event_json = xmltodict.parse(
            win32evtlog.EvtFormatMessage(
                metadata, event, win32evtlog.EvtFormatMessageXml
            )
        )

        # Dataset does not currently support arrays/lists, hence must convert to dicts/objects.
        event_json = _convert_json_array_to_object(event_json)

        # If safe, strip off the @ / # prefixes xmltodict uses to prevent conflicts.
        # Ref: json.dumps(xmltodict.parse('<entry>foo<text>bar</text></entry>'))
        #        => '{"entry": {"text": "bar", "#text": "foo"}}'
        event_json = _strip_xmltodict_prefixes(event_json)

        # FormatMessage will replace insertion and parameter strings in the event message,
        # however it will not replace parameter strings in the event data.
        # Ref: https://learn.microsoft.com/en-us/windows/win32/eventlog/event-identifiers#message-definitions
        #      https://learn.microsoft.com/en-us/windows/win32/eventlog/message-files
        #      FormatMessage of https://github.com/mhammond/pywin32/blob/main/win32/Lib/win32evtlogutil.py
        if self._placeholder_render:
            event_json = self._replace_param_placeholders(event_json)
            if time.time() > self._next_cache_report:
                self._next_cache_report = time.time() + self._cache_report_interval
                self._logger.info(
                    "placeholder param cache size = %d" % len(self._param_cache)
                )
                self._logger.info("dll handle cache size = %d" % len(self._dll_cache))

        # Populate the record here with fields that would normally be added by the log formatter,
        # this avoids having to unmarshal and remarshal later in the log formatter.
        # Refer to the use of DummyFormatter in WindowEventLogMonitor.open_metric_log().
        event_json["timestamp"] = event_json["Event"]["System"]["TimeCreated"][
            "SystemTime"
        ]
        event_json["name"] = self._logger.name
        event_json["monitor"] = "windows_event_log_monitor"
        self._logger.emit_value("unused", scalyr_util.json_encode(event_json))

        self._bookmark_lock.acquire()
        try:
            channel = values[win32evtlog.EvtSystemChannel][0]
            if channel not in self._bookmarks:
                self._bookmarks[channel] = win32evtlog.EvtCreateBookmark(None)
            win32evtlog.EvtUpdateBookmark(self._bookmarks[channel], event)
        finally:
            self._bookmark_lock.release()

    def _param_placeholder_value(self, channel, provider, param):
        if not re.match("^%%[0-9]+$", param):
            return param

        if channel == "Security":
            provider = "Security"

        param_key = "%s-%s-%s" % (channel, provider, param)
        if param_key in self._param_cache:
            return self._param_cache[param_key]

        dll_key = "%s-%s" % (channel, provider)
        if dll_key in self._dll_cache:
            if not isinstance(self._dll_cache[dll_key], _DLL):
                return param
        else:
            # Before opening a new handle to a dll check if another handle to the same dll is open;
            # multiple event log providers may ultimately reference the same dll.

            try:
                dllpath = _DLL.dllpath(channel, provider)
            except Exception as e:
                self._dll_cache[dll_key] = e
                return param

            found = False
            for dll in self._dll_cache.values():
                if not isinstance(dll, _DLL):
                    continue
                if dll.path == dllpath:
                    self._dll_cache[dll_key] = dll
                    found = True
                    break

            if not found:
                try:
                    self._dll_cache[dll_key] = _DLL(channel, provider)
                except Exception as e:
                    self._dll_cache[dll_key] = e
                    self._logger.error(
                        "win32api.LoadLibraryEx exception: %s" % six.text_type(e),
                        limit_once_per_x_secs=self._error_repeat_interval,
                        limit_key="win32api.LoadLibraryEx",
                    )
                    return param

        try:
            value = win32api.FormatMessageW(
                win32con.FORMAT_MESSAGE_FROM_HMODULE,
                self._dll_cache[dll_key].handle,
                int(param[2:]),
                self._langid,
                None,
            )
            self._param_cache[param_key] = value.strip()
        except Exception as e:
            self._param_cache[param_key] = param
            self._logger.error(
                "win32api.FormatMessageW exception: %s" % six.text_type(e),
                limit_once_per_x_secs=self._error_repeat_interval,
                limit_key="win32api.FormatMessageW",
            )

        return self._param_cache[param_key]

    def _replace_param_placeholders(self, event):
        rv = copy.deepcopy(event)

        try:
            event_data = event["Event"]["EventData"]["Data"]
            channel = event["Event"]["System"]["Channel"]
            provider = event["Event"]["System"]["Provider"]["Name"]
        except:
            return rv

        if isinstance(event_data, str) and re.match("^%%[0-9]+$", event_data):
            rv["Event"]["EventData"]["Data"] = self._param_placeholder_value(
                channel, provider, event_data
            )

        elif isinstance(event_data, dict):
            for key, val in event_data.items():
                if isinstance(val, str) and re.match("^%%[0-9]+$", val):
                    rv["Event"]["EventData"]["Data"][
                        key
                    ] = self._param_placeholder_value(channel, provider, val)
                elif (
                    isinstance(val, dict)
                    and "Text" in val
                    and re.match("^%%[0-9]+$", val["Text"])
                ):
                    rv["Event"]["EventData"]["Data"][key][
                        "Text"
                    ] = self._param_placeholder_value(channel, provider, val["Text"])

        return rv


def _convert_json_array_to_object(x):
    if isinstance(x, list):
        # Special handling of @Name fields per customer request:
        # Ie [{"@Name:":"n1", "a1":"v1", ...}, ...] becomes {"n1":{"a1":"v1", ...}, ...}
        # Duplicate @Names are handled by appending the index number if possible.
        # Otherwise the (stringified) index number becomes the field name.
        rv = {}
        for i in range(len(x)):
            if isinstance(x[i], dict) and "@Name" in x[i]:
                orig_name = name = x[i].pop("@Name")
                if name in rv:
                    name += str(i)
                    # Fallback to the original behavior if this pathological case occurs
                    if name in rv:
                        x[i]["@Name"] = orig_name
                        rv[str(i)] = _convert_json_array_to_object(x[i])
                        continue
                rv[name] = _convert_json_array_to_object(x[i])
            else:
                rv[str(i)] = _convert_json_array_to_object(x[i])
        return rv
    elif isinstance(x, dict):
        return {k: _convert_json_array_to_object(v) for k, v in x.items()}
    else:
        return x


def _strip_xmltodict_prefixes(x):
    if isinstance(x, dict):
        rv = {}

        # Sort backwards to ensure non-prefixed keys are handled first
        for k in sorted(x.keys(), reverse=True):
            dest_key = k
            if k[0] == "@" and k[1:] not in rv:
                dest_key = k[1:]
            elif k == "#text" and "Text" not in rv:
                dest_key = "Text"

            rv[dest_key] = _strip_xmltodict_prefixes(x[k])

        return rv

    elif isinstance(x, list):
        return [_strip_xmltodict_prefixes(y) for y in x]
    else:
        return x


class _DLL:
    @staticmethod
    def dllpath(channel, provider):
        keyname = "SYSTEM\\CurrentControlSet\\Services\\EventLog\\%s\\%s" % (
            channel,
            provider,
        )
        keyhandle = win32api.RegOpenKey(win32con.HKEY_LOCAL_MACHINE, keyname)
        try:
            return win32api.ExpandEnvironmentStrings(
                win32api.RegQueryValueEx(keyhandle, "ParameterMessageFile")[0]
            )
        finally:
            win32api.RegCloseKey(keyhandle)

    def __init__(self, channel, provider):
        try:
            self.path = self.dllpath(channel, provider)
            self.handle = win32api.LoadLibraryEx(
                self.path, 0, win32con.LOAD_LIBRARY_AS_DATAFILE
            )
        except Exception as e:
            self.handle = None
            raise e

    def __del__(self):
        if self.handle:
            win32api.FreeLibrary(self.handle)
            self.handle = None


class Cache(collections.OrderedDict):
    """
    Fixed-size cache with entry TTL
    """

    def __init__(self, size, ttl):
        super().__init__()
        self.__size = size
        self.__ttl = ttl

    def __setitem__(self, key, val):
        while len(self) >= self.__size:
            self.popitem(last=False)
        super().__setitem__(key, (val, time.time()))

    def __getitem__(self, key):
        # Intentionally not evicting entries due to ttl here.
        # Expecting checks via __contains__ followed immediately by __getitem__
        val, _ = super().__getitem__(key)
        return val

    def __contains__(self, key):
        try:
            _, added = super().__getitem__(key)
        except KeyError:
            return False

        if time.time() > added + self.__ttl:
            del self[key]
            return False
        return True

    def __iter__(self):
        active = []
        expired = []
        for key in super().__iter__():
            _, added = super().__getitem__(key)

            if time.time() > added + self.__ttl:
                expired += [key]
            else:
                active += [key]

        for key in expired:
            del self[key]
        return iter(active)

    def values(self):
        active_vals = []
        expired_keys = []
        for key in super().__iter__():
            val, added = super().__getitem__(key)

            if time.time() > added + self.__ttl:
                expired_keys += [key]
            else:
                active_vals += [val]

        for key in expired_keys:
            del self[key]
        return iter(active_vals)

    def __len__(self):
        return len(list(iter(self)))


class WindowEventLogMonitor(ScalyrMonitor):
    # fmt: off
    r"""
# Windows Event Log

Import messages from the Windows Event Log.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can import events from multiple channels or sources, for example Application, Security, and System events. You can also filter by event type, for example "System/Level=0" events.

On Windows versions before Vista, 'Critical' events do not exist, and the older EventLog API is used. From Vista onwards, the newer Evt API is used.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Windows server.


2\. Configure the Scalyr Agent to import Event Logs

Open the `agent.json` configuration file, located at `C:\\Program Files (x86)\\Scalyr\\Config`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for the windows event log:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.windows_event_log_monitor",
      }
    ]


### Windows Vista and Later

You can configure the EvtLog API to query events on any channel with XPath. See the
[Event log](https://msdn.microsoft.com/en-us/library/windows/desktop/dd996910.aspx) documentation for more
details. For example:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]

`channels` is a list of `{...}` dict objects, each with `channel` and `query` properties. When not set it defaults to `[ {"channel" : ["Application", "Security", "System"], "query": "*"}]`, which imports all events from the Application, Security, and System channels.

The `channel` property is a list of channels to import events from, and the `query` property is an XPath expression. Events matching the `query`, from the channels in `channel`, are imported. In the above example, the Agent will import Critical (1), Error (2), Warning (3), and Information (4) events from the Application, Security and System channels.

This example imports Critical (1) events for the Application channel; and Critical (1), Error (2), and Warning (3) events for the System and Security channels:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Application"],
              "query": "*[System/Level=1]"
            },
            {
              "channel": ["Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3]"
            }
        ]
      }
    ]


You can also select events with the `<Channel>` tag, in the XML of an event. Go to:

    Run > eventvwr.msc > *select event you want to import* > Event Properties > Details > Select XML

For example, Microsoft-Windows-AAD/Operational events have the tag:

    <Channel>Microsoft-Windows-AAD/Operational</Channel>

To configure the Agent to listen to Critical (1), Error (2), Warning (3), and Information (4) events from this channel:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        channels: [
            { "channel": ["Microsoft-Windows-AAD/Operational"],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]


### Windows Server 2003

For Windows versions earlier than Vista, the Agent uses the older Event Log API.

This example configures the Agent, running on Windows Server 2003, to import Error and Warning level events from
the Application, Security and System sources:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        event_types:             "Error, Warning",
      }
    ]

`sources` is a comma separated list of event sources to import events from. It defaults to `Application, Security, System`. `event_types` is a comma separated list of event types to import. Valid values are: `All` (the default), `Error`, `Warning`, `Information`, `AuditSuccess` and `AuditFailure`. In the above example, only Error and Warning events from Application, Security, and System sources are imported.


3\. (Optional) Set more configuration options

You can format imported events as JSON. Simply add and set `json: true` in the configuration file. For example:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        json: true,
        channels: [
            { "channel": [ "Application", "Security", "System" ],
              "query": "*[System/Level=0 or System/Level=1 or System/Level=2 or System/Level=3 or System/Level=4]"
            }
        ]
      }
    ]


See [Configuration Options](#options) below for more options. You can set a remote domain, server, username, and password; the number of records to read from the end of each log source; and the time to wait before logging similar errors.


4\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for data to send.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into DataSet and query [monitor = 'windows_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27windows_event_log%27). This will show all data collected by this plugin, across all servers.

    """
    # fmt: on

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
        event_api_import_error = ""
        if windll:
            try:
                if windll.wevtapi:
                    evtapi = True
                else:
                    event_api_import_error = "windll.wevtapi attribute doesn't exist"
            except Exception as e:
                event_api_import_error = str(e)
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

            api_class = NewJsonApi if self._config.get("json") else NewApi
            result = api_class(self._config, self._logger, channels)

            if api_class == NewJsonApi:
                self.log_config["parser"] = "dottedEscapedJson"
        else:
            if channels:
                msg = (
                    "Channels are not supported on the older Win32 EventLog API "
                    "(evtapi_available=%s, windll_available=%s, win32_import_error=%s, "
                    "event_api_import_error=%s)."
                    % (
                        evtapi,
                        bool(windll),
                        WIN32_IMPORT_ERROR,
                        str(event_api_import_error),
                    )
                )
                raise Exception(msg)

            result = OldApi(self._config, self._logger, source_list, event_filter)

        return result

    def open_metric_log(self):
        class DummyFormatter(scalyr_logging.MetricLogFormatter):
            def format(self, record):
                # Ensure the LogRecord has a message attribute.
                # If the rate limit is disabled, formatting is not applied by RateLimitLogFilter.
                # Ref: scalyr_logging.MetricLoggingHandler.__init__
                if not hasattr(record, "message"):
                    super(DummyFormatter, self).format(record)
                return record.message[len("unused ") + 1 : -1].replace('\\"', '"')

        rv = super(WindowEventLogMonitor, self).open_metric_log()
        if not rv:
            return rv

        if isinstance(self.__api, NewJsonApi):
            scalyr_logging.MetricLogHandler.get_handler_for_path(
                self.log_config["path"]
            ).setFormatter(DummyFormatter())
        return True

    def run(self):
        self.__load_checkpoints()
        self._check_and_emit_info_and_warning_messages()

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

    def _check_and_emit_info_and_warning_messages(self):
        if isinstance(self.__api, (NewApi, NewJsonApi)):
            self._logger.info("Using new Evt API")

            maximum_records = self._config.get("maximum_records_per_source")
            if (
                maximum_records is not None
                and maximum_records != DEFAULT_MAXIMUM_RECORDS_PER_SOURCE
            ):
                # This option is only applicable when using old API so we emit a warning if this
                # config option is set to a non default value when using a new API
                self._logger.warn(
                    '"maximum_records_per_source" config option is set to a '
                    "non-default value (%s). This config option has no affect when using "
                    "new evt API." % (maximum_records)
                )
        elif isinstance(self.__api, OldApi):
            self._logger.info("Evt API not detected.  Using older EventLog API")
