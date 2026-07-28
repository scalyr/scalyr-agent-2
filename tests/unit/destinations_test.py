# Copyright 2024 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0

from __future__ import unicode_literals
from __future__ import absolute_import

from scalyr_agent import util as scalyr_util
from scalyr_agent.destinations import HecBatch, HecClientSession
from scalyr_agent.scalyr_client import Event

from scalyr_agent.test_base import ScalyrTestCase


def _make_event(thread_id, message, attrs=None, log_attrs=None):
    """Create an Event mimicking the real LogFileProcessor pattern:

    a base Event carrying the log's attributes, then a per-line Event that
    inherits from it via `base=`.
    """
    if log_attrs is not None:
        base = Event(thread_id=thread_id, attrs=log_attrs)
        # Event(base=...) rejects attrs= when non-None; go via add_attributes.
        ev = Event(base=base)
        if attrs:
            ev.add_attributes(attrs, overwrite_existing=True)
    else:
        ev = Event(thread_id=thread_id, attrs=attrs or {})
    ev.set_message(message.encode("utf-8"))
    return ev


class HecBatchEventEndpointTest(ScalyrTestCase):
    def test_add_event_serializes_hec_ndjson(self):
        batch = HecBatch(max_size=64 * 1024, endpoint="event")
        # Per-log attrs supply both HEC metadata (reserved keys) and fields.
        log_attrs = {
            "host": "server1",
            "source": "/var/log/app.log",
            "sourcetype": "app_log",
            "index": "main",
            "team": "backend",
            "parser": "json",
            "logfile": "/var/log/app.log",
        }
        batch.add_log_and_thread("t1", "app", log_attrs)
        ok = batch.add_event(
            _make_event("t1", "hello world", log_attrs=log_attrs),
            timestamp=1_700_000_000_000_000_000,
        )
        self.assertTrue(ok)
        self.assertEqual(batch.num_events, 1)

        events = list(batch._iter_events())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event"], "hello world")
        self.assertAlmostEqual(ev["time"], 1_700_000_000.0)
        # Metadata keys are lifted to top level.
        self.assertEqual(ev["host"], "server1")
        self.assertEqual(ev["source"], "/var/log/app.log")
        self.assertEqual(ev["sourcetype"], "app_log")
        self.assertEqual(ev["index"], "main")
        # Non-metadata attrs from the log entry land in `fields`.
        self.assertEqual(ev["fields"]["team"], "backend")
        self.assertEqual(ev["fields"]["parser"], "json")
        self.assertEqual(ev["fields"]["logfile"], "/var/log/app.log")

    def test_event_attrs_override_log_attrs(self):
        batch = HecBatch(max_size=64 * 1024, endpoint="event")
        log_attrs = {"host": "log-host", "sourcetype": "app_st"}
        batch.add_log_and_thread("t1", "app", log_attrs)
        # Per-event override for `host`.
        batch.add_event(
            _make_event(
                "t1",
                "line",
                attrs={"host": "event-host"},
                log_attrs=log_attrs,
            ),
            timestamp=1_700_000_000_000_000_000,
        )
        ev = list(batch._iter_events())[0]
        self.assertEqual(ev["host"], "event-host")
        self.assertEqual(ev["sourcetype"], "app_st")

    def test_multi_log_batch_does_not_leak_attrs(self):
        """Regression: earlier the single-log fallback mis-attributed events
        from a second log to the first log's attributes."""
        batch = HecBatch(max_size=64 * 1024, endpoint="event")
        log_a = {"sourcetype": "a_st", "source": "/a.log"}
        log_b = {"sourcetype": "b_st", "source": "/b.log"}
        batch.add_log_and_thread("ta", "log_a", log_a)
        batch.add_log_and_thread("tb", "log_b", log_b)
        batch.add_event(
            _make_event("ta", "from a", log_attrs=log_a), timestamp=1
        )
        batch.add_event(
            _make_event("tb", "from b", log_attrs=log_b), timestamp=2
        )
        events = list(batch._iter_events())
        self.assertEqual(events[0]["sourcetype"], "a_st")
        self.assertEqual(events[0]["source"], "/a.log")
        self.assertEqual(events[1]["sourcetype"], "b_st")
        self.assertEqual(events[1]["source"], "/b.log")

    def test_max_size_enforced(self):
        # A batch tiny enough that a single serialized JSON event will not
        # fit; add_event should return False and roll back.
        batch = HecBatch(max_size=10, endpoint="event")
        batch.add_log_and_thread("t1", "app", {})
        ok = batch.add_event(
            _make_event("t1", "this is a longer message that will exceed cap"),
            timestamp=1_700_000_000_000_000_000,
        )
        self.assertFalse(ok)
        self.assertEqual(batch.num_events, 0)
        self.assertEqual(batch.get_payload(), b"")

    def test_position_rollback(self):
        batch = HecBatch(max_size=64 * 1024, endpoint="event")
        batch.add_log_and_thread("t1", "app", {})
        batch.add_event(_make_event("t1", "a"), timestamp=1)
        pos = batch.position()
        batch.add_event(_make_event("t1", "b"), timestamp=2)
        self.assertEqual(batch.num_events, 2)
        batch.set_position(pos)
        self.assertEqual(batch.num_events, 1)
        events = list(batch._iter_events())
        self.assertEqual(events[0]["event"], "a")


class HecBatchRawEndpointTest(ScalyrTestCase):
    def test_raw_endpoint_serializes_plain_lines(self):
        batch = HecBatch(max_size=64 * 1024, endpoint="raw")
        batch.add_log_and_thread(
            "t1", "app", {"host": "h", "sourcetype": "st"}
        )
        batch.add_event(_make_event("t1", "line one"), timestamp=1)
        batch.add_event(_make_event("t1", "line two"), timestamp=2)
        payload = batch.get_payload().decode("utf-8")
        self.assertEqual(payload, "line one\nline two\n")

    def test_raw_metadata_sent_via_query_string(self):
        session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="token123",
            agent_version="test",
            endpoint="raw",
            batch_size=1024,
        )
        # We stub out __send_request via monkey-patching the object; peek at
        # the derived path instead by invoking send with a stub connection.
        captured = {}

        class _StubConn(object):
            def post(self, path, body):
                captured["path"] = path
                captured["body"] = body

            def status_code(self):
                return 200

            def response(self):
                return '{"text":"Success","code":0}'

            def close(self):
                pass

        # Bypass real connect: inject stub.
        session._HecClientSession__connection = _StubConn()

        batch = session.add_events_request()
        # Metadata now comes from the log entry's attributes.
        batch.add_log_and_thread(
            "t1",
            "app",
            {
                "host": "myhost",
                "source": "/a b/log",
                "sourcetype": "app",
                "index": "main",
                "extra": "ignored-in-raw",
            },
        )
        batch.add_event(_make_event("t1", "hello"), timestamp=1)
        status, _, _ = session.send(batch, block_on_response=True)
        self.assertEqual(status, "success")
        self.assertIn("/services/collector/raw?", captured["path"])
        self.assertIn("host=myhost", captured["path"])
        self.assertIn("sourcetype=app", captured["path"])
        self.assertIn("index=main", captured["path"])
        # URL-encoded space in "/a b/log".
        self.assertIn("source=%2Fa%20b%2Flog", captured["path"])
        # Non-reserved attrs are not part of the raw query string.
        self.assertNotIn("extra=", captured["path"])
        self.assertEqual(captured["body"], b"hello\n")


class HecClientSessionTest(ScalyrTestCase):
    def test_auth_and_content_type_headers(self):
        session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="abc-123",
            agent_version="test",
            endpoint="event",
        )
        headers = session._HecClientSession__standard_headers
        self.assertEqual(headers["Authorization"], "Splunk abc-123")
        self.assertEqual(headers["Content-Type"], "application/json")

        raw_session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="abc-123",
            agent_version="test",
            endpoint="raw",
        )
        self.assertEqual(
            raw_session._HecClientSession__standard_headers["Content-Type"],
            "text/plain; charset=utf-8",
        )

    def test_event_endpoint_send_success(self):
        session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="tok",
            agent_version="test",
            endpoint="event",
            batch_size=64 * 1024,
        )

        captured = {}

        class _StubConn(object):
            def post(self, path, body):
                captured["path"] = path
                captured["body"] = body

            def status_code(self):
                return 200

            def response(self):
                return '{"text":"Success","code":0}'

            def close(self):
                pass

        session._HecClientSession__connection = _StubConn()

        batch = session.add_events_request()
        log_attrs = {"host": "h", "parser": "json"}
        batch.add_log_and_thread("t1", "app", log_attrs)
        batch.add_event(
            _make_event("t1", "hi", log_attrs=log_attrs),
            timestamp=1_700_000_000_000_000_000,
        )
        status, _, _ = session.send(batch, block_on_response=True)
        self.assertEqual(status, "success")
        self.assertEqual(captured["path"], "/services/collector/event")
        # Body is NDJSON.
        line = captured["body"].splitlines()[0].decode("utf-8")
        parsed = scalyr_util.json_decode(line)
        self.assertEqual(parsed["event"], "hi")
        self.assertEqual(parsed["host"], "h")
        self.assertEqual(parsed["fields"]["parser"], "json")

    def test_5xx_returns_retryable_status(self):
        session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="tok",
            agent_version="test",
            endpoint="event",
        )

        class _StubConn(object):
            def post(self, path, body):
                pass

            def status_code(self):
                return 503

            def response(self):
                return "unavailable"

            def close(self):
                pass

        session._HecClientSession__connection = _StubConn()
        batch = session.add_events_request()
        batch.add_log_and_thread("t1", "app", {})
        batch.add_event(_make_event("t1", "x"), timestamp=1)
        status, _, _ = session.send(batch, block_on_response=True)
        self.assertEqual(status, "serverTooBusy")

    def test_4xx_returns_drop_status(self):
        session = HecClientSession(
            server_url="https://hec.example.com",
            api_key="tok",
            agent_version="test",
            endpoint="event",
        )

        class _StubConn(object):
            def post(self, path, body):
                pass

            def status_code(self):
                return 401

            def response(self):
                return '{"text":"Invalid token","code":4}'

            def close(self):
                pass

        session._HecClientSession__connection = _StubConn()
        batch = session.add_events_request()
        batch.add_log_and_thread("t1", "app", {})
        batch.add_event(_make_event("t1", "x"), timestamp=1)
        status, _, _ = session.send(batch, block_on_response=True)
        self.assertEqual(status, "error/client/badParam")


class DestinationVirtualSubclassTest(ScalyrTestCase):
    def test_scalyr_client_is_destination(self):
        from scalyr_agent.destinations import Destination
        from scalyr_agent.scalyr_client import ScalyrClientSession

        self.assertTrue(issubclass(ScalyrClientSession, Destination))
