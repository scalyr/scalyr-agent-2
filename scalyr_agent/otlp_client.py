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

import six.moves.http_client

from scalyr_agent.__scalyr__ import SCALYR_VERSION
from scalyr_agent.client_auth import ClientAuth

from scalyr_agent.connection import ConnectionFactory

__author__ = "anthonyj@sentinelone.com"

from opentelemetry.proto.logs.v1.logs_pb2 import ScopeLogs, LogsData, LogRecord, ResourceLogs
from opentelemetry.proto.common.v1.common_pb2 import AnyValue as PB2AnyValue
from opentelemetry.proto.common.v1.common_pb2 import KeyValue as PB2KeyValue
from opentelemetry.proto.common.v1.common_pb2 import (
    KeyValueList as PB2KeyValueList,
)
from opentelemetry.proto.common.v1.common_pb2 import (
    ArrayValue as PB2ArrayValue,
)
from urllib3.util import parse_url
from timeit import default_timer as timer

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
from scalyr_agent.scalyr_client import AddEventsRequest
log = scalyr_logging.getLogger(__name__)

OTLP_LOGS_PATH = "/v1/logs"

log = scalyr_logging.getLogger(__name__)

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

def _encode_attributes(attributes, log_attrs, session_info) -> Optional[List[PB2KeyValue]]:
    attrs_to_send = {}
    if attributes:
        attrs_to_send.update(attributes)
    if session_info:
        attrs_to_send.update(session_info)
    if log_attrs:
        attrs_to_send.update(log_attrs)
    pb2_attributes = []
    for key, value in attrs_to_send.items():
        pb2_attributes.append(_encode_key_value(key, value))
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
    su = server_url
    if server_url is None:
        su = config.server_url
        if "server_url" in worker_config:
            su = worker_config["server_url"]
    log.setLevel(config.debug_level)
    return OTLPClientSession(config, worker_config, su)

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
    def __init__(self, configuration, worker_config, server_url):
        parsed_url = parse_url(server_url + OTLP_LOGS_PATH)
        self.address = parsed_url.scheme + "://" + parsed_url.hostname
        # Append Explicit Port
        if parsed_url.port is not None:
            self.address += ":" + str(parsed_url.port)
        log.info("OTLP Endpoint: %s" %(self.address))
        self.logs_path = parsed_url.path
        log.info("OTLP API Logs Path: %s" % (self.logs_path))
        self.__ca_file = str(configuration.ca_cert_path)
        self.__request_deadline = 60.0
        self.__intermediate_certs_file = str(configuration.intermediate_certs_path)
        self.__use_requests = True

        self.headers = {
            "Connection": "Keep-Alive",
            "Accept": "application/json, application/x-protobuf",
            "Content-Type": "application/x-protobuf",
            "User-Agent": scalyr_util.get_user_agent(
                SCALYR_VERSION, True
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
        self.total_request_latency = 0
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
        result.total_request_latency_secs = self.total_request_latency
        result.total_connections_created = self.total_connections_created
        result.total_compression_time = 0
        return result

    def close(self):
        pass

    def add_events_request(self, session_info=None, max_size=1 * 1024 * 1024 * 1024):
        return OTLPAddEventsRequest(session_info, max_size)

    def send(self, add_events_request, block_on_response=True):
        try:
            if self.__connection is None:
                self.__connection = ConnectionFactory.connection(
                    self.address,
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
            return scalyr_util.wrap_response_if_necessary(
                error_code, 0, "", block_on_response
            )
        self.ensure_auth_session()
        log.log(scalyr_logging.DEBUG_LEVEL_1, "Request Headers: %s" %(self.headers))
        request_body=self.__generate_body(add_events_request)
        start = timer()
        self.__connection.post(self.logs_path, request_body)
        end = timer()
        self.total_request_latency += end - start
        if self.__connection.status_code() == 200:
            self.total_requests_sent+=1
            self.total_request_bytes_sent+=len(request_body)
        else:
            self.total_requests_failed+=1
        return scalyr_util.wrap_response_if_necessary("success", 0, "success", block_on_response)

    def augment_user_agent(self, fragments):
        """Modifies User-Agent header (applies to all data sent to Scalyr)

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        self.headers["User-Agent"] = scalyr_util.get_user_agent(
            SCALYR_VERSION, True, fragments
        )

    def __generate_body(self, add_events_request):
        rl = ResourceLogs()
        sl = ScopeLogs()
        for event in add_events_request.events:
            log_record = self.__event_to_log_record(add_events_request, event)
            sl.log_records.append(log_record)
        rl.scope_logs.append(sl)
        return LogsData(resource_logs=[rl]).SerializeToString()

    def __event_to_log_record(self, add_events_request, event):
        event.attrs.update(add_events_request.log_attrs)
        return LogRecord(time_unix_nano=event.timestamp,
                         body=PB2AnyValue(string_value=event.message),
                         attributes=_encode_attributes(event.attrs, add_events_request.log_attrs, add_events_request.session_info))

class OTLPResponse(object):
    def __init__(self, result):
       self.result = result
    def get_response(self):
        result = "success" if self.result else "failure"
        return (result, 0, result)

class OTLPAddEventsRequest(object):
    def __init__(self, session_info, max_size):
        self.session_info = session_info
        self.max_size = max_size
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
        return self.total_events()

    def increment_timing_data(self, **key_values):
        pass

    def get_timing_data(self):
        return "Timing Data Not Available"
