# Copyright 2014 Scalyr Inc.
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
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import sys
from io import BytesIO

import mock
import time

from scalyr_agent.__scalyr__ import SCALYR_VERSION

from scalyr_agent import scalyr_client
from scalyr_agent import util as scalyr_util
from scalyr_agent.scalyr_client import (
    AddEventsRequest,
    PostFixBuffer,
    EventSequencer,
    Event,
    ScalyrClientSession,
    MAX_REQUEST_BODY_SIZE_LOG_MSG_LIMIT,
)

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase


import scalyr_agent.test_util as test_util


class AddEventsRequestTest(ScalyrTestCase):
    def setUp(self):
        super(AddEventsRequestTest, self).setUp()
        self.__body = {"token": "fakeToken"}

    def test_basic_case(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(
            request.add_event(Event().set_message(b"eventOne"), timestamp=1)
        )
        self.assertTrue(
            request.add_event(Event().set_message(b"eventTwo"), timestamp=2)
        )

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            b""", logs: [], threads: [], client_time: 1 }""",
        )
        self.assertEquals(request.total_events, 2)
        request.close()

    def test_multiple_calls_to_get_payload(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertTrue(
            request.add_event(Event().set_message(b"eventOne"), timestamp=1)
        )
        self.assertTrue(
            request.add_event(Event().set_message(b"eventTwo"), timestamp=2)
        )

        self.assertEquals(request.get_payload(), request.get_payload())
        request.close()

    def test_add_log_and_thread(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(
            request.add_event(Event().set_message(b"eventOne"), timestamp=1)
        )
        self.assertTrue(request.add_log_and_thread("t1", "n1", {"l1": "L1"}))
        self.assertTrue(
            request.add_event(Event().set_message(b"eventTwo"), timestamp=2)
        )
        self.assertTrue(request.add_log_and_thread("t2", "n2", {"l2": "L2"}))

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            b""", logs: [{"attrs":{"l1":"L1"},"id":"t1"},{"attrs":{"l2":"L2"},"id":"t2"}], threads: [{"id":"t1","name":"n1"},{"id":"t2","name":"n2"}], client_time: 1 }""",
        )

        self.assertEquals(request.total_events, 2)
        request.close()

    def test_maximum_bytes_exceeded(self):
        request = AddEventsRequest(self.__body, max_size=112)
        request.set_client_time(1)

        self.assertTrue(request.add_event(Event().set_message("eventOne"), timestamp=1))
        self.assertFalse(
            request.add_event(Event().set_message("eventTwo"), timestamp=2)
        )

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"}], logs: [], threads: [], client_time: 1 }""",
        )
        request.close()

    def test_maximum_bytes_exceeded_from_logs_and_threads(self):
        request = AddEventsRequest(self.__body, max_size=131)
        request.set_client_time(1)

        self.assertTrue(request.add_log_and_thread("t1", "name1", {}))
        self.assertFalse(request.add_log_and_thread("t2", "name2", {}))

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [], logs: [{"attrs":{},"id":"t1"}], threads: [{"id":"t1","name":"name1"}], client_time: 1 }""",
        )

        request.close()

    def test_set_position(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        self.assertTrue(
            request.add_event(Event().set_message(b"eventOne"), timestamp=1)
        )
        self.assertTrue(
            request.add_event(Event().set_message(b"eventTwo"), timestamp=2)
        )

        request.set_position(position)
        self.assertTrue(
            request.add_event(Event().set_message(b"eventThree"), timestamp=3)
        )

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\neventThree},ts:"3"}], logs: [], threads: [], client_time: 1 }""",
        )

        request.close()

    def test_set_position_with_log_and_thread(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        request.add_log_and_thread("log1", "Hi there", {})
        self.assertTrue(request.add_event(Event().set_message("eventOne"), timestamp=1))
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=2))

        request.set_position(position)
        self.assertTrue(request.add_log_and_thread("log2", "Log two", {}))
        self.assertTrue(
            request.add_event(Event().set_message("eventThree"), timestamp=3)
        )

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\neventThree},ts:"3"}], """
            b"""logs: [{"attrs":{},"id":"log2"}], threads: [{"id":"log2","name":"Log two"}], client_time: 1 }""",
        )

        request.close()

    def test_set_log_line_attributes(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        request.add_log_and_thread("log2", "Log two", {})

        event_one = Event().set_message("eventOne")
        event_one.add_attributes({"source": "stdout"}, overwrite_existing=True)

        self.assertTrue(request.add_event(event_one, timestamp=1))

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{"source":"stdout",message:`s\x00\x00\x00\x08eventOne},ts:"1"}], """
            b"""logs: [{"attrs":{},"id":"log2"}], threads: [{"id":"log2","name":"Log two"}], client_time: 1 }""",
        )

        request.close()

    def test_set_log_line_attributes_with_base_attributes(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        request.add_log_and_thread("log2", "Log two", {})

        event_base = Event()
        event_base.add_attributes(
            {"source": "stdout", "base": "base"}, overwrite_existing=False
        )

        event_one = Event(base=event_base)
        event_one.set_message("eventOne")
        event_one.add_attributes(
            {"source": "stdin", "event": "event"}, overwrite_existing=True
        )

        self.assertTrue(request.add_event(event_one, timestamp=1))

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{"event":"event","source":"stdin",message:`s\x00\x00\x00\x08eventOne},ts:"1"}], """
            b"""logs: [{"attrs":{},"id":"log2"}], threads: [{"id":"log2","name":"Log two"}], client_time: 1 }""",
        )
        request.close()

    def test_set_client_time(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(100)

        self.assertTrue(request.add_event(Event().set_message("eventOne"), timestamp=1))
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=2))

        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            b""", logs: [], threads: [], client_time: 100 }""",
        )

        request.set_client_time(2)
        self.assertEquals(
            request.get_payload(),
            b"""{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            b""", logs: [], threads: [], client_time: 2 }""",
        )
        request.close()

    def test_monotonically_increasing_timestamp(self):
        request = AddEventsRequest(self.__body, enforce_monotonic_timestamps=True)
        scalyr_client._set_last_timestamp(0)

        ts = 2000

        expected = str(ts + 1)

        self.assertTrue(
            request.add_event(Event().set_message("eventOne"), timestamp=ts)
        )
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=1))

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][1]
        self.assertEquals(event["ts"], expected)

    def test_no_monotonically_increasing_timestamp(self):
        request = AddEventsRequest(self.__body)

        ts = 2000

        self.assertTrue(
            request.add_event(Event().set_message("eventOne"), timestamp=ts)
        )
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=1))

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][1]
        self.assertEquals(event["ts"], "1")

    def test_timestamp_none(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(100)

        ts = int(time.time() * 1e9)

        self.assertTrue(
            request.add_event(Event().set_message("eventOne"), timestamp=None)
        )

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][0]
        event_ts = int(event["ts"])
        threshold = abs(event_ts - ts)

        # allow a threshold of 1 second to have elapsed between reading the time.time and
        # setting the event timestamp in add_event
        self.assertTrue(threshold < 1e9)

    def test_sequence_id_but_no_number(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"), timestamp=1, sequence_id=1234
            )
        )
        self.assertEquals(request.total_events, 1)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][0]

        self.assertFalse("si" in event)
        self.assertFalse("sn" in event)
        self.assertFalse("sd" in event)
        request.close()

    def test_sequence_number_but_no_id(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"), timestamp=1, sequence_number=1234
            )
        )
        self.assertEquals(request.total_events, 1)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][0]

        self.assertFalse("si" in event)
        self.assertFalse("sn" in event)
        self.assertFalse("sd" in event)
        request.close()

    def test_sequence_id_and_number(self):
        expected_id = "1234"
        expected_number = 1234
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"),
                timestamp=1,
                sequence_id=expected_id,
                sequence_number=expected_number,
            )
        )
        self.assertEquals(request.total_events, 1)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][0]

        self.assertEquals(expected_id, event["si"])
        self.assertEquals(expected_number, event["sn"])
        self.assertFalse("sd" in event)
        request.close()

    def test_same_sequence_id(self):
        expected_id = b"1234"
        expected_number = 1234
        expected_delta = 1
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"),
                timestamp=1,
                sequence_id=expected_id,
                sequence_number=expected_number,
            )
        )
        self.assertTrue(
            request.add_event(
                Event().set_message("eventTwo"),
                timestamp=2,
                sequence_id=expected_id,
                sequence_number=expected_number + expected_delta,
            )
        )
        self.assertEquals(request.total_events, 2)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][1]

        self.assertFalse("si" in event)
        self.assertFalse("sn" in event)
        self.assertEquals(expected_delta, event["sd"])
        request.close()

    def test_different_sequence_id(self):
        first_id = "1234"
        second_id = "1235"
        first_number = 1234
        second_number = 1234
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"),
                timestamp=1,
                sequence_id=first_id,
                sequence_number=first_number,
            )
        )
        self.assertTrue(
            request.add_event(
                Event().set_message("eventTwo"),
                timestamp=2,
                sequence_id=first_id,
                sequence_number=first_number + 1,
            )
        )
        self.assertTrue(
            request.add_event(
                Event().set_message("eventThree"),
                timestamp=3,
                sequence_id=second_id,
                sequence_number=second_number,
            )
        )
        self.assertEquals(request.total_events, 3)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][2]

        self.assertEquals(second_id, event["si"])
        self.assertEquals(second_number, event["sn"])
        self.assertFalse("sd" in event)
        request.close()

    def test_exceeds_size_doesnt_effect_sequence(self):
        first_id = "1234"
        second_id = "1235"
        first_number = 1234
        second_number = 4321
        expected_delta = 10
        request = AddEventsRequest(self.__body, max_size=180)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"),
                timestamp=1,
                sequence_id=first_id,
                sequence_number=first_number,
            )
        )
        self.assertFalse(
            request.add_event(
                Event(
                    attrs={"name": "eventTwo", "long": "some really long text"}
                ).set_message(b"eventTwo"),
                timestamp=2,
                sequence_id=second_id,
                sequence_number=second_number,
            )
        )
        self.assertTrue(
            request.add_event(
                Event().set_message(b"eventThree"),
                timestamp=3,
                sequence_id=first_id,
                sequence_number=first_number + expected_delta,
            )
        )
        self.assertEquals(request.total_events, 2)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][1]

        self.assertFalse("si" in event)
        self.assertEquals(expected_delta, event["sd"])
        self.assertFalse("sn" in event)
        request.close()

    def test_set_position_resets_sequence_compression(self):
        first_id = "1234"
        first_number = 1234
        second_number = 4321
        expected_delta = 10
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventOne"),
                timestamp=1,
                sequence_id=first_id,
                sequence_number=first_number,
            )
        )
        position = request.position()
        self.assertTrue(
            request.add_event(
                Event().set_message("eventTwo"),
                timestamp=2,
                sequence_id=first_id,
                sequence_number=first_number + expected_delta,
            )
        )
        request.set_position(position)
        self.assertTrue(
            request.add_event(
                Event().set_message("eventThree"),
                timestamp=3,
                sequence_id=first_id,
                sequence_number=second_number,
            )
        )
        self.assertEquals(request.total_events, 2)

        json = test_util.parse_scalyr_request(request.get_payload())
        event = json["events"][1]

        self.assertEquals(second_number, event["sn"])
        self.assertFalse("sd" in event)
        request.close()

    def test_timing_data(self):
        request = AddEventsRequest(self.__body)
        request.increment_timing_data(**{"foo": 1, "bar": 2})
        request.increment_timing_data(foo=5)

        # can't rely on stable order in "get_timing_data()" return value
        self.assertEquals(sorted(request.get_timing_data()), sorted("foo=6.0 bar=2.0"))


class EventTest(ScalyrTestCase):
    def test_all_fields(self):
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message(b"my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue(),
        )

        self.assertEquals(
            {
                "log": "foo",
                "thread": "foo",
                "ts": "42",
                "si": "1",
                "sn": 2,
                "sd": 3,
                "attrs": {"parser": "bar", "message": "my_message", "sample_rate": 0.5},
            },
            test_util.parse_scalyr_request(output_buffer.getvalue()),
        )

    def test_fast_path_fields(self):
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message(b"my_message")
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sd:3,ts:"42"}',
            output_buffer.getvalue(),
        )

    def test_individual_fields(self):
        # snd
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message(b"my_message")
        x.set_sequence_number_delta(3)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sd:3}',
            output_buffer.getvalue(),
        )

        # timestamp
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},ts:"42"}',
            output_buffer.getvalue(),
        )

        # sampling_rate
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sampling_rate(0.5)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5}}',
            output_buffer.getvalue(),
        )

        # sid
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sequence_id("hi")

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},si:"hi"}',
            output_buffer.getvalue(),
        )

        # seq num
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sequence_number(5)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sn:5}',
            output_buffer.getvalue(),
        )

    def test_only_message(self):
        x = Event()
        x.set_message("my_message")

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b"{attrs:{message:`s\x00\x00\x00\nmy_message}}", output_buffer.getvalue()
        )

    def test_no_thread_id(self):
        x = Event(attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue(),
        )

    def test_no_attrs(self):
        x = Event(thread_id="biz")
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"biz", log:"biz", attrs:{message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue(),
        )

    def test_create_from_template(self):
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x = Event(base=x)
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue(),
        )

    def test_create_from_template_with_add_attributes(self):
        x = Event(thread_id="foo", attrs={"parser": "bar"})
        x = Event(base=x)
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42)

        x.add_attributes({"trigger_update": "yes"})

        output_buffer = BytesIO()
        x.serialize(output_buffer)

        self.assertEquals(
            b'{thread:"foo", log:"foo", attrs:{"trigger_update":"yes",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue(),
        )


class EventSequencerTest(ScalyrTestCase):
    def setUp(self):
        super(EventSequencerTest, self).setUp()
        self.event_sequencer = EventSequencer()

    def test_sequence_id_but_no_number(self):

        event = Event()
        self.event_sequencer.add_sequence_fields(event, "1234", None)
        self.assertIsNone(event.sequence_id)
        self.assertIsNone(event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)

    def test_sequence_number_but_no_id(self):
        event = Event()
        self.event_sequencer.add_sequence_fields(event, None, 1234)

        self.assertIsNone(event.sequence_id)
        self.assertIsNone(event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)

    def test_sequence_id_and_number(self):
        expected_id = "1234"
        expected_number = 1234
        event = Event()
        self.event_sequencer.add_sequence_fields(event, expected_id, expected_number)

        self.assertEquals(expected_id.encode("utf-8"), event.sequence_id)
        self.assertEquals(expected_number, event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)

    def test_same_sequence_id(self):
        expected_id = "1234"
        expected_number = 1234
        expected_delta = 1

        event = Event()
        self.event_sequencer.add_sequence_fields(event, expected_id, expected_number)

        event = Event()
        self.event_sequencer.add_sequence_fields(
            event, expected_id, expected_number + expected_delta
        )

        self.assertIsNone(event.sequence_id)
        self.assertIsNone(event.sequence_number)
        self.assertEqual(expected_delta, event.sequence_number_delta)

    def test_different_sequence_id(self):
        first_id = "1234"
        second_id = "1235"
        first_number = 1234
        second_number = 1234

        event = Event()
        self.event_sequencer.add_sequence_fields(event, first_id, first_number)

        event = Event()
        self.event_sequencer.add_sequence_fields(event, first_id, first_number + 1)

        event = Event()
        self.event_sequencer.add_sequence_fields(event, second_id, second_number)

        self.assertEquals(second_id.encode("utf-8"), event.sequence_id)
        self.assertEquals(second_number, event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)

    def test_memento(self):
        first_id = "1234"
        second_id = "1235"
        first_number = 1234
        second_number = 1234

        event = Event()
        self.event_sequencer.add_sequence_fields(event, first_id, first_number)

        memento = self.event_sequencer.get_memento()

        event = Event()
        self.event_sequencer.add_sequence_fields(event, second_id, second_number)
        self.assertIsNotNone(event.sequence_id)
        self.assertIsNotNone(event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)

        self.event_sequencer.restore_from_memento(memento)

        event = Event()
        self.event_sequencer.add_sequence_fields(event, first_id, first_number + 1)
        self.assertIsNone(event.sequence_id)
        self.assertIsNone(event.sequence_number)
        self.assertIsNotNone(event.sequence_number_delta)

    def test_reset(self):
        expected_id = "1234"
        expected_number = 1234
        expected_delta = 1

        event = Event()
        self.event_sequencer.add_sequence_fields(event, expected_id, expected_number)

        self.event_sequencer.reset()
        event = Event()
        self.event_sequencer.add_sequence_fields(
            event, expected_id, expected_number + expected_delta
        )

        self.assertEqual(expected_id.encode("utf-8"), event.sequence_id)
        self.assertEqual(expected_number + expected_delta, event.sequence_number)
        self.assertIsNone(event.sequence_number_delta)


class PostFixBufferTest(ScalyrTestCase):
    def setUp(self):
        super(PostFixBufferTest, self).setUp()
        self.__format = b"], logs: LOGS, threads: THREADS, client_time: TIMESTAMP }"

    def test_basic_case(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        test_buffer.add_log_and_thread_entry("log_5", "histogram_builder", {})
        self.assertEquals(
            test_buffer.content(),
            b"""], logs: [{"attrs":{},"id":"log_5"}], threads: [{"id":"log_5","name":"histogram_builder"}], client_time: 1 }""",
        )

    def test_set_client_time(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)
        self.assertTrue(test_buffer.set_client_timestamp(433423))

        expected_length = test_buffer.length

        content = test_buffer.content(cache_size=False)

        self.assertEquals(content, b"], logs: [], threads: [], client_time: 433423 }")
        self.assertEquals(expected_length, len(content))

    def test_set_client_time_fail(self):
        test_buffer = PostFixBuffer(self.__format)
        self.assertTrue(
            test_buffer.set_client_timestamp(1, fail_if_buffer_exceeds=1000000)
        )
        self.assertFalse(
            test_buffer.set_client_timestamp(
                433423, fail_if_buffer_exceeds=test_buffer.length + 3
            )
        )

        expected_length = test_buffer.length

        content = test_buffer.content(cache_size=False)

        self.assertEquals(content, b"], logs: [], threads: [], client_time: 1 }")
        self.assertEquals(expected_length, len(content))

    def test_add_thread(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        self.assertTrue(
            test_buffer.add_log_and_thread_entry("log_5", "histogram_builder", {})
        )

        # NOTE: Order is important since .length call depends on the cached size
        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertTrue(
            test_buffer.add_log_and_thread_entry("log_12", "ok_builder", {})
        )

        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertTrue(
            test_buffer.add_log_and_thread_entry("log", "histogram_builder_foo", {})
        )

        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertEquals(
            test_buffer.content(),
            b"""], logs: [{"attrs":{},"id":"log_5"},{"attrs":{},"id":"log_12"},{"attrs":{},"id":"log"}], """
            b"""threads: [{"id":"log_5","name":"histogram_builder"},"""
            b"""{"id":"log_12","name":"ok_builder"},"""
            b"""{"id":"log","name":"histogram_builder_foo"}], client_time: 1 }""",
        )

    def test_add_thread_fail(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        # NOTE: Order is important since .length call depends on the cached size
        self.assertTrue(
            test_buffer.add_log_and_thread_entry(
                "log_5", "histogram_builder", {}, fail_if_buffer_exceeds=1000000
            )
        )

        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertFalse(
            test_buffer.add_log_and_thread_entry(
                "log_6", "histogram", {}, fail_if_buffer_exceeds=10
            )
        )

        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertEquals(
            test_buffer.content(),
            b"""], logs: [{"attrs":{},"id":"log_5"}], """
            b"""threads: [{"id":"log_5","name":"histogram_builder"}], client_time: 1 }""",
        )

    def test_set_position(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        self.assertTrue(
            test_buffer.add_log_and_thread_entry("log_5", "histogram_builder", {})
        )

        position = test_buffer.position

        self.assertTrue(
            test_buffer.add_log_and_thread_entry("log_6", "histogram2_builder", {})
        )

        test_buffer.set_position(position)

        content = test_buffer.content(cache_size=True)
        length = test_buffer.length

        self.assertEquals(
            length,
            len(content),
            "Buffer content: %s" % (test_buffer.content(cache_size=False)),
        )

        self.assertEquals(
            test_buffer.content(),
            b"""], logs: [{"attrs":{},"id":"log_5"}], threads: [{"id":"log_5","name":"histogram_builder"}], """
            b"""client_time: 1 }""",
        )


class ClientSessionTest(BaseScalyrLogCaptureTestCase):
    def test_user_agent_callback(self):
        session = ScalyrClientSession(
            "https://dummserver.com", "DUMMY API KEY", SCALYR_VERSION
        )

        def get_user_agent():
            return session._ScalyrClientSession__standard_headers["User-Agent"]

        base_ua = get_user_agent()
        frags = ["frag1", "frag2", "frag3"]
        session.augment_user_agent(frags)
        self.assertEquals(get_user_agent(), base_ua + ";" + ";".join(frags))

    @mock.patch("scalyr_agent.scalyr_client.time.time", mock.Mock(return_value=0))
    def test_send_request_body_is_logged_raw_uncompressed(self):
        """
        When sending a request with compression available / enabled, raw (uncompressed) request
        body (payload) should be logged under DEBUG log level.
        """
        session = ScalyrClientSession(
            "https://dummserver.com", "DUMMY API KEY", SCALYR_VERSION
        )

        session._ScalyrClientSession__connection = mock.Mock()
        session._ScalyrClientSession__receive_response = mock.Mock()
        session._ScalyrClientSession__compress = mock.Mock(return_value="compressed")

        add_events_request = AddEventsRequest({"foo": "bar"})
        event1 = Event(thread_id="foo1", attrs={"parser": "bar1"}).set_message(
            "eventOne"
        )
        event2 = Event(thread_id="foo2", attrs={"parser": "bar2"}).set_message(
            "eventTwo"
        )
        add_events_request.add_event(event=event1, timestamp=1)
        add_events_request.add_event(event=event2, timestamp=2)

        session.send(add_events_request=add_events_request)

        # Should log raw (uncompressed) request body / payload
        expected_body = r'{"foo":"bar", events: \[{thread:"foo1", .*'
        self.assertLogFileContainsRegex(
            expected_body, file_path=self.agent_debug_log_path
        )
        expected_body = r'.*,{thread:"foo2", log:"foo2", attrs:{"parser":"bar2",.*'
        self.assertLogFileContainsRegex(
            expected_body, file_path=self.agent_debug_log_path
        )

        # Verify that the compression was indeed enabled since that's the scenario we are testing
        call_kwargs = session._ScalyrClientSession__connection.post.call_args_list[0][1]
        self.assertEqual(call_kwargs["body"], "compressed")

    @mock.patch("scalyr_agent.scalyr_client.time.time", mock.Mock(return_value=0))
    def test_send_request_timestamp_doesnt_increases_monotonically(self):
        session = ScalyrClientSession(
            "https://dummserver.com", "DUMMY API KEY", SCALYR_VERSION,
        )

        session._ScalyrClientSession__connection = mock.Mock()
        session._ScalyrClientSession__receive_response = mock.Mock()

        add_events_request = session.add_events_request()

        ts = 2000

        add_events_request.add_event(Event().set_message("eventOne"), timestamp=ts)
        add_events_request.add_event(Event().set_message("eventTwo"), timestamp=1)

        json = test_util.parse_scalyr_request(add_events_request.get_payload())
        event = json["events"][1]
        self.assertEquals(event["ts"], "1")

    @mock.patch("scalyr_agent.scalyr_client.time.time", mock.Mock(return_value=0))
    def test_send_request_timestamp_increases_monotonically(self):
        session = ScalyrClientSession(
            "https://dummserver.com",
            "DUMMY API KEY",
            SCALYR_VERSION,
            enforce_monotonic_timestamps=True,
        )

        session._ScalyrClientSession__connection = mock.Mock()
        session._ScalyrClientSession__receive_response = mock.Mock()
        scalyr_client._set_last_timestamp(0)

        add_events_request = session.add_events_request()

        ts = 2000
        expected = str(ts + 1)

        add_events_request.add_event(Event().set_message("eventOne"), timestamp=ts)
        add_events_request.add_event(Event().set_message("eventTwo"), timestamp=1)

        json = test_util.parse_scalyr_request(add_events_request.get_payload())
        event = json["events"][1]
        self.assertEquals(event["ts"], expected)

    @mock.patch("scalyr_agent.scalyr_client.time.time", mock.Mock(return_value=0))
    def test_send_request_body_is_logged_raw_uncompressed_long_body_is_truncated(self):
        # Verify that very large bodies are truncated to avoid increased memory usage issues under
        # Python 2.7
        session = ScalyrClientSession(
            "https://dummserver.com", "DUMMY API KEY", SCALYR_VERSION
        )

        session._ScalyrClientSession__connection = mock.Mock()
        session._ScalyrClientSession__receive_response = mock.Mock()
        session._ScalyrClientSession__compress = mock.Mock(return_value="compressed")

        add_events_request = AddEventsRequest({"bar": "baz"})
        event1 = Event(thread_id="foo4", attrs={"parser": "bar2"}).set_message(
            "a" * (MAX_REQUEST_BODY_SIZE_LOG_MSG_LIMIT + 1)
        )

        add_events_request.add_event(event=event1, timestamp=1)

        session.send(add_events_request=add_events_request)

        # Should log raw (uncompressed) request body / payload
        expected_body = (
            r'Sending POST /addEvents with body "{"bar":"baz".*\.\.\. \[body truncated to %s chars\] \.\.\.'
            % (MAX_REQUEST_BODY_SIZE_LOG_MSG_LIMIT)
        )
        self.assertLogFileContainsRegex(
            expected_body, file_path=self.agent_debug_log_path
        )

    @mock.patch("scalyr_agent.scalyr_client.time.time", mock.Mock(return_value=0))
    def test_send_request_body_compression(self):
        add_events_request = AddEventsRequest({"bar": "baz"})
        event1 = Event(thread_id="foo4", attrs={"parser": "bar2"}).set_message(
            "test message 1"
        )
        event2 = Event(thread_id="foo5", attrs={"parser": "bar2"}).set_message(
            "test message 2"
        )
        add_events_request.add_event(event=event1, timestamp=1)
        add_events_request.add_event(event=event2, timestamp=2)

        serialized_data = add_events_request.get_payload()

        if sys.version_info < (2, 7, 0):
            # lz4 and zstandard Python package is not available for Python 2.6
            compression_types = scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL.copy()
            del compression_types["zstandard"]
            del compression_types["lz4"]
        else:
            compression_types = scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL

        for compression_type in compression_types:
            session = ScalyrClientSession(
                "https://dummserver.com",
                "DUMMY API KEY",
                SCALYR_VERSION,
                compression_type=compression_type,
            )

            session._ScalyrClientSession__connection = mock.Mock()
            session._ScalyrClientSession__receive_response = mock.Mock()

            session.send(add_events_request=add_events_request)

            (
                path,
                request,
            ) = session._ScalyrClientSession__connection.post.call_args_list[0]

            _, decompress_func = scalyr_util.get_compress_and_decompress_func(
                compression_type
            )

            self.assertEqual(path[0], "/addEvents")
            self.assertEqual(
                session._ScalyrClientSession__standard_headers["Content-Encoding"],
                compression_type,
            )

            # Verify decompressed data matches the raw body
            self.assertTrue(b"test message 1" not in request["body"])
            self.assertTrue(b"test message 2" not in request["body"])
            self.assertFalse(serialized_data == request["body"])
            self.assertEqual(serialized_data, decompress_func(request["body"]))

        # Compression is disabled
        session = ScalyrClientSession(
            "https://dummserver.com",
            "DUMMY API KEY",
            SCALYR_VERSION,
            compression_type=None,
        )

        session._ScalyrClientSession__connection = mock.Mock()
        session._ScalyrClientSession__receive_response = mock.Mock()

        session.send(add_events_request=add_events_request)

        serialized_data = add_events_request.get_payload()

        (path, request,) = session._ScalyrClientSession__connection.post.call_args_list[
            0
        ]

        _, decompress_func = scalyr_util.get_compress_and_decompress_func(
            compression_type
        )

        self.assertEqual(path[0], "/addEvents")

        self.assertTrue(b"test message 1" in request["body"])
        self.assertTrue(b"test message 2" in request["body"])
        self.assertEqual(serialized_data, request["body"])
        self.assertTrue(
            "Content-Encoding" not in session._ScalyrClientSession__standard_headers
        )
