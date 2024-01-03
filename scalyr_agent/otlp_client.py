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

from typing import Dict, Optional, Sequence

from opentelemetry.sdk.resources import _EMPTY_RESOURCE
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.sdk._logs import LogData, LogRecord
from opentelemetry.exporter.otlp.proto.http._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor



__author__ = "anthonyj@sentinelone.com"

import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.client_auth import ClientAuth
from scalyr_agent.scalyr_client import AddEventsRequest

log = scalyr_logging.getLogger(__name__)

# This client is able to communicate payloads via OTLP HTTP protocol.
# This does not support all the features of the Scalyr Client as we currently rely on the OpenTelemetry
# Python SDK for transport and batching.
#
# Limitations
# - We likely have some conditions where events would be lost.
# - Some Statistics and Timing data are not implemented.
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
        self.total_requests_sent = 0
        self.total_requests_failed = 0
        self.total_request_bytes_sent = 0
        self.pending_request_bytes_sent = 0
        self.configuration = configuration
        self.headers = {}
        self.auth = ClientAuth(self.configuration, self.headers)
        self.exporter = ScalyrOTLPLogExporter(server_url, headers=self.headers)
        schedule_delay_millis = configuration.min_request_spacing_interval * 1000
        if schedule_delay_millis <= 0:
            schedule_delay_millis = 1000
        self.batch_processor = BatchLogRecordProcessor(self.exporter, schedule_delay_millis)

    def ensure_auth_session(self):
        return self.auth.authenticate()

    # TODO: Find a way to get statistics from the opentelemetry library
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
        self.batch_processor.shutdown()
    
    def augment_user_agent(self, fragments):
        pass

    def add_events_request(self, session_info=None, max_size=1 * 1024 * 1024 * 1024):
        return OTLPAddEventsRequest(self.batch_processor)

    def send(self, add_events_request, block_on_response=True):
        self.ensure_auth_session()
        res = self.batch_processor.force_flush()
        if res == True:
            self.total_requests_sent += 1
            self.total_request_bytes_sent += add_events_request.current_size
            add_events_request.set_events_size(0, 0)
        else:
            self.total_requests_failed += 1
        return OTLPResponse(res).get_response

class OTLPResponse(object):
    def __init__(self, result):
       self.result = result
    def get_response(self):
        result = "success" if self.result else "failure"
        return (result, 0, result)

class OTLPAddEventsRequest(object):
    def __init__(self, batch_processor):
        self.current_size = 0
        self.total_events = 0
        self.thread_id = None
        self.thread_name = None
        self.log_attrs = None
        self.events = []
        self.__receive_response_status = None
        self.batch_processor = batch_processor

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
        self.batch_processor.emit(LogData(LogRecord(resource=_EMPTY_RESOURCE, attributes={}, severity_number=SeverityNumber.UNSPECIFIED, trace_flags=0, trace_id=0, span_id=0, timestamp=timestamp, body=event.message.decode("utf-8")), InstrumentationScope("scalyr-agent")))
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

class ScalyrOTLPLogExporter(OTLPLogExporter):
    def __init__(self, server_url, headers):
        self.headers = headers
        OTLPLogExporter.__init__(self, server_url, headers=self.headers)

    # OTLP Log Exporter only sets headers once on __init__
    def export(self, batch: Sequence[LogData]):
        self._session.headers.update(self.headers)
        OTLPLogExporter.export(self, batch)

