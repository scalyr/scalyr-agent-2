"""
This module is used to print additional debug statements for the log-processing abstractions when they read log lines
for a particular log file.
"""

from __future__ import unicode_literals

from __future__ import absolute_import
import io
import logging
import os
import re
import tempfile

from scalyr_agent import scalyr_logging, line_matcher, log_processing, scalyr_client
from scalyr_agent import configuration
from scalyr_agent import compat

from scalyr_agent.platform_controller import PlatformController

log = scalyr_logging.getLogger(__name__)

# The prefix for the pod which lines have to be tracked.
POD_NAME = "lwbi-exporter-"

# the kubernetes monitor will write the id of the needed contained in this variable.
CONTAINER_ID = None

file_logger = None

original_set_log_destination = scalyr_logging.set_log_destination

def scalyr_logging_set_log_destination(*args, **kwargs):
    global file_logger
    original_set_log_destination(*args, **kwargs)
    file_logger = logging.getLogger("PAYLOAD")

    path = os.path.join(
        tempfile.gettempdir(),
        "debug_payload.log"
    )
    file_handler = logging.FileHandler(filename=path)
    file_logger.addHandler(file_handler)

scalyr_logging.set_log_destination = scalyr_logging_set_log_destination


def create_message(method):
    """

    Create base message with the base fields.

    """
    data_str = "METHOD: {0}".format(method)

    return data_str


def log_message(method, logger, message):
    """
    Log custom message.
    """
    logger.info(", ".join([create_message(method), message]))


def print_line_data(method, logger, line, print_line=False, additional_data=None):
    """
    Log info about the log line.
    """
    data_str = create_message(method)

    count = len(line)

    data_str = ", ".join([data_str, "COUNT: {0}".format(count)])

    if print_line:
        data_str = ", ".join([data_str, "LINE: {0}".format(line)])

    if additional_data is None:
        additional_data = {}

    for k, v in additional_data.items():
        data_str = ", ".join([data_str, "{0}: {1}".format(k.upper(), v)])

    logger.info(data_str)


class DebugConfiguration(configuration.Configuration):
    """
    The subclass of the configuration needed to specify additional debug options.
    """

    def __init__(self, *args, **kwargs):
        super(DebugConfiguration, self).__init__(*args, **kwargs)

    def parse(self):
        global POD_NAME
        super(DebugConfiguration, self).parse()
        self._Configuration__verify_or_set_optional_string(
            self._Configuration__config,
            "_debug_log_path",
            POD_NAME,
            "",
            env_aware=True,
        )

        POD_NAME = self._debug_log_path

    @property
    def _debug_log_path(self):
        return self._Configuration__get_config().get_string("_debug_log_path")


class DebugMixin:
    """
    The debug purpose class which is used to add debug logic to log-processing abstractions.
    """

    def __init__(self):
        # logger to write debug statements.
        self._debug_logger = log

        # only print debug statements if log-processing abstractions are processing this file.
        self._debug_log_path = None

        # global config.
        self._config = None

    def set_debug_attributes(self, log_file_path, config):
        self._debug_log_path = log_file_path
        self._config = config

    @property
    def is_not_debug_file(self):
        """
        Return if the current file is the file that is being tracked.
        """
        global CONTAINER_ID
        if CONTAINER_ID is None:
            return True

        return CONTAINER_ID not in self._debug_log_path


class DebugLineMatcher(line_matcher.LineMatcher, DebugMixin):
    """
    Debug version for the LineMatcher
    """

    def _readline(self, *args, **kwargs):
        result = super(DebugLineMatcher, self)._readline(*args, **kwargs)

        if self.is_not_debug_file:
            # the current file is not what we want, skip.
            return result

        line, partial = result

        print_line_data(
            "LogMatcher._readline",
            log,
            line,
            print_line=True,
            additional_data={"partial": partial},
        )

        return result

    def readline(self, *args, **kwargs):
        result = super(DebugLineMatcher, self).readline(*args, **kwargs)
        if self.is_not_debug_file:
            return result

        print_line_data(
            "LogMatcher.readline", log, result,
        )

        return result


class DebugLogFileIterator(log_processing.LogFileIterator, DebugMixin):
    """
    Debug version for the LogFileIterator
    """

    def __init__(self, path, config, *args, **kwargs):
        super(DebugLogFileIterator, self).__init__(path, config, *args, **kwargs)
        self._LogFileIterator__line_matcher.set_debug_attributes(
            self._LogFileIterator__path, config
        )

    def readline(self, *args, **kwargs):
        result = super(DebugLogFileIterator, self).readline(*args, **kwargs)
        if self.is_not_debug_file:
            return result

        log_message(
            "LogFileIterator.readline",
            log,
            "PARSE_FORMAT: {0}".format(self._LogFileIterator__parse_format),
        )

        print_line_data(
            "LogFileIterator.readline", log, result.line,
        )

        return result


class DebugLogFileProcessor(log_processing.LogFileProcessor, DebugMixin):
    """
    Debug version for the LogFileProcessor
    """

    def __init__(self, path, config, *args, **kwargs):
        super(DebugLogFileProcessor, self).__init__(path, config, *args, **kwargs)
        self.set_debug_attributes(path, config)
        self._LogFileProcessor__log_file_iterator.set_debug_attributes(path, config)

    def __create_events_object(self, *args, **kwargs):
        event = super(DebugLogFileProcessor, self)._create_events_object(
            *args, **kwargs
        )

        if self.is_not_debug_file:
            return event

        print_line_data(
            "LogFileProcessor._create_events_object",
            log,
            event.message,
            additional_data={"attrs": event.attrs},
        )

        return event

    def _create_events_object(self, *args, **kwargs):
        event = self.__create_events_object(*args, **kwargs)
        event.set_debug_attributes(self._LogFileProcessor__path, self._config)

        return event


class DebugEvent(scalyr_client.Event, DebugMixin):
    def __init__(self, *args, **kwargs):
        super(DebugEvent, self).__init__(*args, **kwargs)

    def serialize(self, output_buffer):
        buffer = io.BytesIO()
        super(DebugEvent, self).serialize(buffer)
        output_buffer.write(buffer.getvalue())

        if self.is_not_debug_file:
            return

        serialized_data = buffer.getvalue()

        i = serialized_data.find(b"message:`s")

        size_substr = serialized_data[i + 10 : i + 14]

        (size,) = compat.struct_unpack_unicode(">I", size_substr)

        line = serialized_data[i + 14 : i + 14 + size]

        print_line_data(
            "Event.serialize", log, line,
        )

class DebugAddEventRequest(scalyr_client.AddEventsRequest, DebugMixin):

    # pattern to find the threads list at the end of the payload. This will help to determine if needed container logs
    # are presented in the current request payload
    SEARCH_PATTERN = re.compile(r"threads:\s+(\[.+\]),\s+client_time")
    def get_payload(self):
        global CONTAINER_ID

        result = super(DebugAddEventRequest, self).get_payload()

        payload = result.decode("utf-8", "replace")

        if CONTAINER_ID is None:
            return result

        m = type(self).SEARCH_PATTERN.search(payload)
        if m:
            threads_string, = m.groups(1)

            if CONTAINER_ID in threads_string:
                if file_logger:
                    log_message(
                        "AddEventsRequest.get_payload", file_logger, payload
                    )

        return result

from scalyr_agent import line_matcher
from scalyr_agent import log_processing
from scalyr_agent import scalyr_client


# replace original classes with debug versions.
configuration.Configuration = DebugConfiguration  # type: ignore
scalyr_client.AddEventsRequest = DebugAddEventRequest  # type: ignore
log_processing.Event = DebugEvent  # type: ignore
scalyr_client.Event = DebugEvent  # type: ignore
log_processing.LogFileIterator = DebugLogFileIterator  # type: ignore
log_processing.LogFileProcessor = DebugLogFileProcessor  # type: ignore
line_matcher.LineMatcher = DebugLineMatcher  # type: ignore