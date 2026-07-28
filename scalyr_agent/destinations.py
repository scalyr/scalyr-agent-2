# Copyright 2024 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# Pluggable destination layer.
#
# Introduces a `Destination` abstraction so the agent can ship log events to
# either the Scalyr `/addEvents` endpoint (default; via ScalyrClientSession)
# or a Splunk HTTP Event Collector (via HecClientSession) based on the hidden
# `destination` configuration option. Both implementations expose the same
# duck-typed interface used by `copying_manager/worker.py`:
#
#     - `add_events_request(session_info=..., max_size=...) -> Batch`
#     - `send(batch, block_on_response=False) -> callable | tuple`
#     - `generate_status()`
#     - `session_id`, `close()`, `augment_user_agent()`, `ping()`
#
# The `Batch` object returned from `add_events_request` is duck-compatible
# with `scalyr_client.AddEventsRequest` so `LogFileProcessor.perform_processing`
# works unchanged.

from __future__ import absolute_import

import abc
import io
import time

import six

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
from scalyr_agent.connection import ConnectionFactory
from scalyr_agent.util import verify_and_get_compress_func

log = scalyr_logging.getLogger(__name__)


# Keys that get lifted from `hec_attributes` (or per-log attrs) into top-level
# HEC event metadata. All other keys are folded into the HEC `fields` object.
_HEC_METADATA_KEYS = ("host", "source", "sourcetype", "index")


class Destination(six.with_metaclass(abc.ABCMeta, object)):
    """Abstract base documenting the destination interface.

    Concrete implementations register themselves as virtual subclasses so
    isinstance() checks work without forcing inheritance.
    """

    @abc.abstractmethod
    def add_events_request(self, session_info=None, max_size=1 * 1024 * 1024):
        pass

    @abc.abstractmethod
    def send(self, batch, block_on_response=True):
        pass

    @abc.abstractmethod
    def generate_status(self):
        pass

    @property
    @abc.abstractmethod
    def session_id(self):
        pass

    @abc.abstractmethod
    def close(self, current_time=None):
        pass

    def augment_user_agent(self, fragments):
        pass

    def ping(self):
        return "success"

    def perform_agent_version_check(self, track="stable"):
        return None


class HecBatch(object):
    """Duck-typed analogue of `scalyr_client.AddEventsRequest` that serializes
    events as newline-delimited HEC JSON (event endpoint) or plain text lines
    (raw endpoint).

    Populated by `LogFileProcessor.perform_processing` through the same
    `add_log_and_thread` / `add_event` / `position` / `set_position` contract
    that `AddEventsRequest` supports.
    """

    class Position(object):
        __slots__ = ("events", "buffer_size", "thread_ids")

        def __init__(self, events, buffer_size, thread_ids):
            self.events = events
            self.buffer_size = buffer_size
            self.thread_ids = thread_ids

    def __init__(self, max_size, endpoint, session_info=None):
        self.__max_size = max_size
        self.__endpoint = endpoint
        self.__session_info = dict(session_info or {})

        # Per-thread log attrs registered via `add_log_and_thread`. Not
        # serialized to the wire directly; used at `add_event` time to compose
        # the HEC event payload's metadata and fields.
        self.__log_attrs_by_thread = {}

        self.__buffer = io.BytesIO()
        self.__events_added = 0
        self.__body = None
        self.__timing_data = {}
        self.__client_time = None

    # Interface used by the sender ------------------------------------------

    def set_client_time(self, current_time):
        self.__client_time = current_time

    def get_payload(self):
        if self.__body is None:
            self.__body = self.__buffer.getvalue()
        return self.__body

    def close(self):
        self.__buffer = None

    # Interface used by LogFileProcessor.perform_processing -----------------

    @property
    def current_size(self):
        if self.__buffer is not None:
            return self.__buffer.tell()
        return len(self.__body or b"")

    @property
    def num_events(self):
        return self.__events_added

    def total_events(self):
        return self.__events_added

    def add_log_and_thread(self, thread_id, thread_name, log_attrs):
        # Log/thread registration consumes no wire bytes for HEC, so we can
        # never blow past `max_size` here.
        self.__log_attrs_by_thread[thread_id] = dict(log_attrs or {})
        return True

    def raw_metadata(self):
        """Return the HEC metadata dict to send as query-string params on the
        raw endpoint. Derived from the first registered log's attributes.

        If multiple logs are batched together in raw mode their metadata is
        assumed to match; only the first log's reserved keys are used.
        """
        if not self.__log_attrs_by_thread:
            return {}
        first_attrs = next(iter(self.__log_attrs_by_thread.values()))
        return {
            k: v for k, v in first_attrs.items() if k in _HEC_METADATA_KEYS
        }

    def add_event(self, event, timestamp=None, sequence_id=None, sequence_number=None):
        if self.__buffer is None:
            raise RuntimeError("HecBatch: cannot add events after close.")

        start_pos = self.__buffer.tell()

        raw_msg = event.message
        if isinstance(raw_msg, (bytes, bytearray)):
            message = raw_msg.decode("utf-8", "replace")
        elif raw_msg is None:
            message = ""
        else:
            message = raw_msg

        # `Event.attrs` already merges the log's base attributes (registered
        # in the parent `Event` when the log's LogFileProcessor was created)
        # with per-event overrides. That means the log entry's `attributes:
        # {}` block flows naturally into `event.attrs`, so we do not need a
        # separate per-thread lookup here. Doing so would mis-attribute
        # events to the wrong log when a batch mixes multiple log files.
        event_attrs = event.attrs or {}

        if self.__endpoint == "raw":
            line = message.rstrip("\n").encode("utf-8") + b"\n"
            self.__buffer.write(line)
        else:
            hec_event = self.__build_hec_event(message, timestamp, event_attrs)
            self.__buffer.write(scalyr_util.json_encode(hec_event, binary=True))
            self.__buffer.write(b"\n")

        if self.__buffer.tell() > self.__max_size:
            self.__buffer.truncate(start_pos)
            self.__buffer.seek(start_pos)
            return False

        self.__events_added += 1
        return True

    def __build_hec_event(self, message, timestamp, event_attrs):
        # Timestamps arrive in ns (scalyr convention); HEC expects epoch secs.
        if timestamp is not None:
            time_val = timestamp / 1e9
        else:
            time_val = time.time()

        hec_event = {"time": time_val, "event": message}
        fields = {}

        def _apply(src):
            if not src:
                return
            for key, value in src.items():
                if key in _HEC_METADATA_KEYS:
                    hec_event[key] = value
                elif key == "message":
                    continue
                else:
                    fields[key] = value

        # Precedence (later overwrites earlier): sessionInfo -> event attrs.
        # `event.attrs` already merges the log's `attributes: {}` block (via
        # the event's parent) with any per-event overrides. Reserved keys
        # (host/source/sourcetype/index) are lifted to HEC top-level
        # metadata; everything else lands in HEC `fields`.
        _apply(self.__session_info)
        _apply(event_attrs)

        if fields:
            hec_event["fields"] = fields
        return hec_event

    # Rollback + timing ------------------------------------------------------

    def position(self):
        return HecBatch.Position(
            self.__events_added,
            self.__buffer.tell(),
            list(self.__log_attrs_by_thread.keys()),
        )

    def set_position(self, position):
        self.__buffer.truncate(position.buffer_size)
        self.__buffer.seek(position.buffer_size)
        self.__events_added = position.events
        keep = set(position.thread_ids)
        for key in list(self.__log_attrs_by_thread.keys()):
            if key not in keep:
                del self.__log_attrs_by_thread[key]

    def increment_timing_data(self, **key_values):
        for key, value in key_values.items():
            self.__timing_data[key] = self.__timing_data.get(key, 0) + value

    def get_timing_data(self):
        return " ".join(
            "%s=%s" % (k, v) for k, v in sorted(self.__timing_data.items())
        )

    # Test helpers -----------------------------------------------------------

    def _iter_events(self):
        """Yield each serialized event line (JSON dict for event endpoint,
        raw text for raw endpoint). Used only by tests.
        """
        payload = self.get_payload()
        for line in payload.split(b"\n"):
            if not line:
                continue
            text = line.decode("utf-8")
            if self.__endpoint == "raw":
                yield text
            else:
                yield scalyr_util.json_decode(text)


def _wrap_response(status, bytes_sent, response, block_on_response):
    if block_on_response:
        return status, bytes_sent, response

    def wrap():
        return status, bytes_sent, response

    return wrap


def _url_quote(value):
    from urllib.parse import quote

    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return quote(str(value), safe="")


class HecClientSession(Destination):
    """HEC destination implementation.

    Reuses `ConnectionFactory` for HTTP(S) transport and the shared
    compression pipeline. Authentication is via `Authorization: Splunk
    <api_key>`. No indexer acknowledgment is performed in this version.
    """

    def __init__(
        self,
        server_url,
        api_key,
        agent_version,
        endpoint="event",
        batch_size=1 * 1024 * 1024,
        quiet=False,
        request_deadline=60.0,
        ca_file=None,
        intermediate_certs_file=None,
        use_requests_lib=False,
        proxies=None,
        compression_type=None,
        compression_level=9,
        disable_send_requests=False,
    ):
        if not quiet:
            log.info('Using "%s" as HEC endpoint (mode=%s)' % (server_url, endpoint))

        self.__server_url = server_url
        self.__api_key = api_key
        self.__endpoint = endpoint
        self.__batch_size = batch_size
        self.__request_deadline = request_deadline
        self.__ca_file = ca_file
        self.__intermediate_certs_file = intermediate_certs_file
        self.__use_requests = use_requests_lib
        self.__proxies = proxies
        self.__quiet = quiet
        self.__disable_send_requests = disable_send_requests
        self.__agent_version = agent_version

        self.__session_id = scalyr_util.create_unique_id()

        # Compression setup mirrors ScalyrClientSession.
        self.__compression_type = compression_type
        self.__compression_level = compression_level
        self.__compress = None
        encoding = None
        if compression_type and compression_type != "none":
            fn = verify_and_get_compress_func(compression_type, compression_level)
            if fn:
                self.__compress = fn
                encoding = compression_type
            else:
                log.warning(
                    "'%s' compression not available for HEC destination; "
                    "sending uncompressed." % compression_type
                )

        self.__standard_headers = {
            "Connection": "Keep-Alive",
            "Accept": "application/json",
            "Authorization": "Splunk %s" % api_key,
            "Content-Type": (
                "application/json"
                if endpoint == "event"
                else "text/plain; charset=utf-8"
            ),
            "User-Agent": "scalyr-agent-2/%s hec-destination" % agent_version,
        }
        if encoding:
            self.__standard_headers["Content-Encoding"] = encoding

        self.__connection = None
        self.__last_connection_close = None

        # Counters mirror `ScalyrClientSession`'s so the existing status
        # logging in `copying_manager/worker.py` works unchanged.
        self.total_requests_sent = 0
        self.total_requests_failed = 0
        self.total_request_bytes_sent = 0
        self.total_compressed_request_bytes_sent = 0
        self.total_response_bytes_received = 0
        self.total_request_latency_secs = 0
        self.total_connections_created = 0
        self.total_compression_time = 0

    @property
    def session_id(self):
        return self.__session_id

    def generate_status(self):
        from scalyr_agent.scalyr_client import ScalyrClientSessionStatus

        result = ScalyrClientSessionStatus()
        result.total_requests_sent = self.total_requests_sent
        result.total_requests_failed = self.total_requests_failed
        result.total_request_bytes_sent = self.total_request_bytes_sent
        result.total_compressed_request_bytes_sent = (
            self.total_compressed_request_bytes_sent
        )
        result.total_response_bytes_received = self.total_response_bytes_received
        result.total_request_latency_secs = self.total_request_latency_secs
        result.total_connections_created = self.total_connections_created
        result.total_compression_time = self.total_compression_time
        return result

    def augment_user_agent(self, fragments):
        base = "scalyr-agent-2/%s hec-destination" % self.__agent_version
        if fragments:
            base += ";" + ";".join(map(str, fragments))
        self.__standard_headers["User-Agent"] = base

    def add_events_request(self, session_info=None, max_size=None):
        # `SCALYR_HEC_BATCH_SIZE` is authoritative for HEC. We ignore the
        # `max_size` argument that the worker derives from
        # `max_allowed_request_size` so the operator can size HEC batches
        # independently from the /addEvents-oriented default.
        return HecBatch(
            max_size=self.__batch_size,
            endpoint=self.__endpoint,
            session_info=session_info,
        )

    def send(self, batch, block_on_response=True):
        # Skip empty batches. Unlike the /addEvents endpoint (which treats an
        # empty events array as a keep-alive), HEC servers typically reject a
        # zero-byte POST with HTTP 415. Reporting "success" here lets the
        # copying manager treat this as a no-op iteration.
        if batch.num_events == 0:
            return _wrap_response("success", 0, "", block_on_response)

        path = "/services/collector/event"
        if self.__endpoint == "raw":
            path = "/services/collector/raw"
            # Raw endpoint takes metadata via query params. Derive them from
            # the first log registered on the batch (which is populated from
            # the log entry's `attributes: {}` block).
            metadata = batch.raw_metadata()
            params = []
            for key in _HEC_METADATA_KEYS:
                if key in metadata:
                    params.append("%s=%s" % (key, _url_quote(metadata[key])))
            if params:
                path = path + "?" + "&".join(params)

        body = batch.get_payload()
        return self.__send_request(
            path, body=body, block_on_response=block_on_response
        )

    def close(self, current_time=None):
        if self.__connection is not None:
            if current_time is None:
                current_time = time.time()
            try:
                self.__connection.close()
            except Exception:
                pass
            self.__connection = None
            self.__last_connection_close = current_time

    def __send_request(self, path, body, block_on_response=True):
        current_time = time.time()

        if (
            self.__last_connection_close is not None
            and current_time - self.__last_connection_close < 30
        ):
            return _wrap_response(
                "client/connectionClosed", 0, "", block_on_response
            )

        self.total_requests_sent += 1
        was_sent = False

        try:
            try:
                if self.__connection is None:
                    self.__connection = ConnectionFactory.connection(
                        self.__server_url,
                        self.__request_deadline,
                        self.__ca_file,
                        self.__intermediate_certs_file,
                        self.__standard_headers,
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
                return _wrap_response(error_code, 0, "", block_on_response)

            self.total_request_bytes_sent += len(body) + len(path)

            body_to_send = body
            if self.__compress and body:
                start = time.time()
                body_to_send = self.__compress(body)
                self.total_compression_time += time.time() - start

            self.total_compressed_request_bytes_sent += (
                len(body_to_send) + len(path)
            )

            try:
                if self.__disable_send_requests:
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_0,
                        "HEC send requests disabled. %d bytes dropped"
                        % len(body_to_send),
                        limit_once_per_x_secs=60,
                        limit_key="hec-send-requests-disabled",
                    )
                else:
                    self.__connection.post(path, body=body_to_send)
            except Exception as error:
                log.warning(
                    "HEC post to %s failed: %s" % (self.__server_url, str(error)),
                    error_code="client/requestFailed",
                )
                return _wrap_response(
                    "requestFailed", len(body_to_send), "", block_on_response
                )

            was_sent = True

            def receive():
                return self.__receive_response(body_to_send, current_time)

            if block_on_response:
                return receive()
            return receive
        finally:
            if not was_sent:
                self.total_request_latency_secs += time.time() - current_time
                self.total_requests_failed += 1
                self.close(current_time=current_time)

    def __receive_response(self, body_str, send_time):
        response = ""
        was_success = False
        bytes_received = 0
        try:
            try:
                if self.__disable_send_requests:
                    response = '{"text":"Success","code":0}'
                    status_code = 200
                else:
                    status_code = self.__connection.status_code()
                    response = self.__connection.response()
                bytes_received = len(response) if response else 0
            except Exception as error:
                log.warning(
                    "Failed to receive HEC response: %s" % str(error),
                    error_code="requestFailed",
                )
                return "requestFailed", len(body_str), response

            try:
                response = six.ensure_text(response, "utf-8", "ignore")
            except Exception:
                pass

            if status_code == 200:
                was_success = True
                # HEC returns {"text":"Success","code":0}. Normalize to
                # "success" so the shared worker status-check code path is
                # unchanged.
                return "success", len(body_str), response
            if status_code == 429 or (500 <= status_code < 600):
                log.warning(
                    "HEC returned status %s; will re-attempt" % status_code,
                    error_code="serverTooBusy",
                )
                return "serverTooBusy", len(body_str), response

            log.error(
                "HEC request failed with status %s. Response: %s"
                % (
                    status_code,
                    scalyr_util.remove_newlines_and_truncate(response, 500),
                ),
                error_code="error/client/badParam",
            )
            return "error/client/badParam", len(body_str), response
        finally:
            self.total_request_latency_secs += time.time() - send_time
            if not was_success:
                self.total_requests_failed += 1
                self.close(current_time=send_time)
            self.total_response_bytes_received += bytes_received
