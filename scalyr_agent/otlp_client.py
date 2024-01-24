# Copyright 2023 SentinelOne, Inc
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

from __future__ import unicode_literals
from __future__ import absolute_import

from typing import Any, Mapping, Optional, List

import sys, platform, ssl

import six
from six.moves import map
import six.moves.http_client

from scalyr_agent.__scalyr__ import SCALYR_VERSION
from scalyr_agent.client_auth import ClientAuth

from scalyr_agent.connection import ConnectionFactory

__author__ = "anthonyj@sentinelone.com"

import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.third_party.opentelemetry.proto.logs.v1.logs_pb2 import ScopeLogs, LogsData, LogRecord, ResourceLogs
from scalyr_agent.third_party.opentelemetry.proto.common.v1.common_pb2 import AnyValue as PB2AnyValue
from scalyr_agent.third_party.opentelemetry.proto.common.v1.common_pb2 import KeyValue as PB2KeyValue
from scalyr_agent.third_party.opentelemetry.proto.common.v1.common_pb2 import (
    KeyValueList as PB2KeyValueList,
)
from scalyr_agent.third_party.opentelemetry.proto.common.v1.common_pb2 import (
    ArrayValue as PB2ArrayValue,
)


from scalyr_agent.scalyr_client import AddEventsRequest
log = scalyr_logging.getLogger(__name__)

OTLP_LOGS_PATH = "/v1/logs"

# OTLP Protobuf Helpers
def _encode_value(value: Any) -> PB2AnyValue:
    if isinstance(value, bool):
        return PB2AnyValue(bool_value=value)
    if isinstance(value, str):
        return PB2AnyValue(string_value=value)
    if isinstance(value, int):
        return PB2AnyValue(int_value=value)
    if isinstance(value, float):
        return PB2AnyValue(double_value=value)
    if isinstance(value, Sequence):
        return PB2AnyValue(
            array_value=PB2ArrayValue(values=[_encode_value(v) for v in value])
        )
    elif isinstance(value, Mapping):
        return PB2AnyValue(
            kvlist_value=PB2KeyValueList(
                values=[_encode_key_value(str(k), v) for k, v in value.items()]
            )
        )
    raise Exception(f"Invalid type {type(value)} of value {value}")


def _encode_key_value(key: str, value: Any) -> PB2KeyValue:
    return PB2KeyValue(key=key, value=_encode_value(value))

def _encode_attributes(attributes) -> Optional[List[PB2KeyValue]]:
    if attributes:
        pb2_attributes = []
        for key, value in attributes.items():
            pb2_attributes.append(_encode_key_value(key, value))
    else:
        pb2_attributes = None
    return pb2_attributes


# This client is able to communicate payloads via OTLP HTTP protocol.
# Limitations
#
# - We likely have some conditions where events would be lost.
# - Most Statistics and Timing data are not implemented.
def create_otlp_client(config, worker_config, server_url=None):
    """Creates and returns a new OTLP client to an OpenTelemetry Collector.
    @param quiet: If true, only errors should be written to stdout.
    @param config: The agent configuration object used for dynamically loading up auth patterns
    @param server_url: The URL to the OTLP server. If None, use default scalyr_server value from config"""
    if server_url == None:
        server_url = config.server_url + "/v1/logs"
    return OTLPClientSession(config, server_url)

class ScalyrClientSessionStatus(object):
    def __init__(self):
        self.total_requests_sent = None
        self.total_requests_failed = None
        self.total_request_bytes_sent = None
        self.total_compressed_request_bytes_sent = None
        self.total_response_bytes_received = None
        self.total_request_latency_secs = None
        self.total_connections_created = None
        self.total_compression_time = None


class OTLPClientSession(object):
    def __init__(self, configuration, server_url=None):
        self.__full_address = configuration.server_url
        self.__ca_file = str(configuration.ca_cert_path)
        self.__request_deadline = 60.0
        self.__intermediate_certs_file = str(configuration.intermediate_certs_path)
        self.__use_requests = True
        self.headers = {
            "Connection": "Keep-Alive",
            "Accept": "application/json, application/x-protobuf",
            "Content-Type": "application/x-protobuf",
            "User-Agent": self.__get_user_agent(
                SCALYR_VERSION
            ),
        }
        self.__connection = None
        self.__quiet = False
        self.__proxies = configuration.network_proxies
        self.total_requests_sent = 0
        self.total_requests_failed = 0
        self.total_request_bytes_sent = 0
        self.pending_request_bytes_sent = 0
        self.total_connections_created = 0
        self.configuration = configuration
        self.auth = ClientAuth(self.configuration, self.headers)
        self.exporter = None # ScalyrOTLPLogExporter(server_url, headers=self.headers)
        schedule_delay_millis = configuration.min_request_spacing_interval * 1000
        if schedule_delay_millis <= 0:
            schedule_delay_millis = 1000
    def ensure_auth_session(self):
        return self.auth.authenticate()

    def generate_status(self):
        result = ScalyrClientSessionStatus()
        result.total_requests_sent = self.total_requests_sent
        result.total_requests_failed = self.total_requests_failed
        result.total_request_bytes_sent = self.total_request_bytes_sent
        result.total_compressed_request_bytes_sent = 0
        result.total_response_bytes_received = 0
        result.total_request_latency_secs = 0
        result.total_connections_created = 0
        result.total_compression_time = 0
        return result

    def close(self):
        pass

    def add_events_request(self, session_info=None, max_size=1 * 1024 * 1024 * 1024):
        return OTLPAddEventsRequest()

    def send(self, add_events_request, block_on_response=True):
        try:
            if self.__connection is None:
                self.__connection = ConnectionFactory.connection(
                    self.__full_address,
                    self.__request_deadline,
                    self.__ca_file,
                    self.__intermediate_certs_file,
                    self.headers,
                    self.__use_requests,
                    quiet=self.__quiet,
                    proxies=self.__proxies,
                )
                self.total_connections_created += 1
        except Exception as e:
            error_code = (
                    getattr(e, "error_code", "client/connectionFailed")
                    or "client/connectionFailed"
            )
            return self.__wrap_response_if_necessary(
                error_code, 0, "", block_on_response
            )
        self.ensure_auth_session()

        self.__connection.post(OTLP_LOGS_PATH, self.__generate_body(add_events_request))
        res = self.__connection.response()
        return self.__wrap_response_if_necessary("success", 0, "success", block_on_response
)

    def augment_user_agent(self, fragments):
        """Modifies User-Agent header (applies to all data sent to Scalyr)

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        self.headers["User-Agent"] = self.__get_user_agent(
            SCALYR_VERSION, fragments
        )

    def __generate_body(self, add_events_request):
        rl = ResourceLogs()
        sl = ScopeLogs()
        for event in add_events_request.events:
            log_record = self.__event_to_log_record(event)
            sl.log_records.append(log_record)
        rl.scope_logs.append(sl)
        return LogsData(resource_logs=[rl]).SerializeToString()

    def __event_to_log_record(self, event):
        return LogRecord(time_unix_nano=event.timestamp,
                         body=PB2AnyValue(string_value=event.message),
                         attributes=_encode_attributes(event.attrs))

    def __get_user_agent(
            self, agent_version, fragments=None, sessions_api_keys_tuple=None
    ):
        """Determine the user agent to report in the request headers.

        We construct an agent that gives Scalyr some information about the platform the customer is running on,
        the Python version, and a few other tidbits.  This is used to make decisions about support issues.

        @param agent_version: The agent version number.
        @param fragments: Additional strings to be appended. Each will be preceded by a semicolon
        @type agent_version: six.text_type
        @type fragments: List of six.text_type

        @return: The user agent string.
        @rtype: six.text_type
        """
        # We will construct our agent string to look something like:
        # Linux-redhat-7.0;python-2.7.2;agent-2.0.1;ssllib
        # And for requests using requests library:
        # Linux-redhat-7.0;python-2.7.2;agent-2.0.1;ssllib;requests-2.22.0

        python_version = sys.version_info
        if len(python_version) >= 5:
            python_version_str = "python-%s.%s.%s" % (
                python_version[0],
                python_version[1],
                python_version[2],
            )
        else:
            python_version_str = "python-unknown"

        # Try for a linux distribution first.  This doesn't seem to work for Amazon AMIs, but for most
        # distributions it hopefully will provide something readable.
        platform_value = None
        # noinspection PyBroadException
        try:
            distribution = platform.dist()  # pylint: disable=no-member
            if len(distribution[0]) > 0:
                platform_value = "Linux-%s-%s" % (distribution[0], distribution[1])
        except Exception:
            platform_value = None

        # Try Mac
        if platform_value is None:
            # noinspection PyBroadException
            try:
                mac_ver = platform.mac_ver()[0]
                if len(mac_ver) > 0:
                    platform_value = "MacOS-%s" % mac_ver
            except Exception:
                platform_value = None

        # Fall back for all others.  This should print out something reasonable for
        # Windows.
        if platform_value is None:
            platform_value = platform.platform(terse=1)

        # Include openssl version if available
        # Returns a tuple like this: (1, 1, 1, 8, 15)
        openssl_version = getattr(ssl, "OPENSSL_VERSION_INFO", None)
        if openssl_version:
            try:
                openssl_version_string = (
                        ".".join([str(v) for v in openssl_version[:3]])
                        + "-"
                        + str(openssl_version[3])
                )
                openssl_version_string = "o-%s" % (openssl_version_string)
            except Exception:
                openssl_version_string = None
        else:
            openssl_version_string = None

        # Include a string which indicates if the agent is running admin / root user
        from scalyr_agent.platform_controller import PlatformController

        try:
            platform_controller = PlatformController.new_platform()
            current_user = platform_controller.get_current_user()
        except Exception:
            # In some tests on Windows this can throw inside the tests so we ignore the error
            current_user = "unknown"

        if current_user in ["root", "Administrator"] or current_user.endswith(
                "\\Administrators"
        ):
            # Indicates agent running as a privileged / admin user
            user_string = "a-1"
        else:
            # Indicates agent running as a regular user
            user_string = "a-0"

        sharded_copy_manager_string = ""

        # Possible values for this header fragment:
        # mw-0 - Sharded copy manager functionality is disabled
        # mw-1|<num_sessions>|<num_api_keys> - Functionality is enabled and there are <num_sessions>
        # thread based sessions configured with <num_api_keys> unique API keys.
        # mw-2|<num_sessions>|<num_api_keys> - Functionality is enabled and there are <num_sessions>
        # process based sessions configured with <num_api_keys> unique API keys.
        if (
                sessions_api_keys_tuple
                and isinstance(sessions_api_keys_tuple, tuple)
                and len(sessions_api_keys_tuple) == 3
                and sessions_api_keys_tuple[1] > 1
        ):
            (
                worker_type,
                workers_count,
                api_keys_count,
            ) = sessions_api_keys_tuple

            if worker_type == "multiprocess":
                sharded_copy_manager_string = "mw-2|"
            else:
                sharded_copy_manager_string = "mw-1|"

            sharded_copy_manager_string += "%s|%s" % (workers_count, api_keys_count)
        else:
            sharded_copy_manager_string = "mw-0"

        parts = [
            platform_value,
            python_version_str,
            "agent-%s" % agent_version,
        ]

        if openssl_version_string:
            parts.append(openssl_version_string)

        if user_string:
            parts.append(user_string)

        if sharded_copy_manager_string:
            parts.append(sharded_copy_manager_string)

        if self.__use_requests:
            import requests

            parts.append("requests-%s" % (requests.__version__))

        if fragments:
            parts.extend(fragments)
        return ";".join(map(six.text_type, parts))

    def __wrap_response_if_necessary(
        self, status_message, bytes_sent, response, block_on_response
    ):
        """Wraps the response as appropriate based on whether or not the caller is expecting to block on the
        response or not.

        If the caller requested to not block on the response, then they are expecting a function to be returned
        that, when invoked, will block and return the result.  If the caller did requested to block on the response,
        then the response should be returned directly.

        This is used to cover cases where there was an error and we do not have to block on the response from
        the server.  Instead, we already have the response to return.  However, we still need to return the
        right type of object to the caller.

        @param status_message: The status message for the response.
        @param bytes_sent: The number of bytes that were sent.
        @param response: The response to return.
        @param block_on_response: Whether or not the caller requested to block, waiting for the response.  This controls
            whether or not a function is returned or just the response tuple directly.

        @type status_message: str
        @type bytes_sent: int
        @type response: str
        @type block_on_response: bool

        @return: Either a func or a response tuple (status message, num of bytes sent, response body) depending on
            the value of ``block_on_response``.
        @rtype: func or (str, int, str)
        """
        if block_on_response:
            return status_message, bytes_sent, response

        def wrap():
            return status_message, bytes_sent, response

        return wrap


class OTLPResponse(object):
    def __init__(self, result):
       self.result = result
    def get_response(self):
        result = "success" if self.result else "failure"
        return (result, 0, result)

class OTLPAddEventsRequest(object):
    def __init__(self):
        self.current_size = 0
        self.total_events = 0
        self.thread_id = None
        self.thread_name = None
        self.log_attrs = None
        self.events = []
        self.__receive_response_status = None

    def set_events_size(self, total_events, size):
        self.current_size = size
        self.total_events = total_events

    def position(self):
        return AddEventsRequest.Position(
            self.total_events, self.current_size, 0
        )

    def set_position(self, position):
        pass

    def add_log_and_thread(self, thread_id, thread_name, log_attrs):
        self.thread_id = thread_id
        self.thread_name = thread_name
        self.log_attrs = log_attrs
        return True

    def add_event(self, event, timestamp=None, sequence_id=None, sequence_number=None):
        self.current_size += len(event.message)
        self.total_events += 1
        self.events.append(event)
        return True

    def num_events(self):
        self.current_size

    def set_client_time(self, current_time):
        pass

    def get_payload(self):
        pass

    def close(self):
        pass

    def get_timing_data(self):
        pass

    def total_events(self):
        return 0

    def increment_timing_data(self, **key_values):
        pass

    def get_timing_data(self):
        return "Timing Data Not Available"
