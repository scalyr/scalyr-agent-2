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

__author__ = 'czerwin@scalyr.com'

from cStringIO import StringIO

from scalyr_agent.__scalyr__ import SCALYR_VERSION

from scalyr_agent import scalyr_client
from scalyr_agent.scalyr_client import AddEventsRequest, PostFixBuffer, EventSequencer, Event, ScalyrClientSession
from scalyr_agent import json_lib
from scalyr_agent.test_base import ScalyrTestCase
import unittest


class AddEventsRequestTest(ScalyrTestCase):

    def setUp(self):
        self.__body = {'token': 'fakeToken'}

    def test_basic_case(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(request.add_event(Event().set_message("eventOne"), timestamp=1L))
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            """, threads: [], client_time: 1 }""")
        self.assertEquals(request.total_events, 2)
        request.close()

    def test_multiple_calls_to_get_payload(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L))

        self.assertEquals(request.get_payload(), request.get_payload())
        request.close()

    def test_add_thread(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(request.add_event(Event().set_message("eventOne"), timestamp=1L))
        self.assertTrue(request.add_thread('t1', 'n1'))
        self.assertTrue(request.add_event(Event().set_message("eventTwo"), timestamp=2L))
        self.assertTrue(request.add_thread('t2', 'n2'))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            """, threads: [{"id":"t1","name":"n1"},{"id":"t2","name":"n2"}], client_time: 1 }""")

        self.assertEquals(request.total_events, 2)
        request.close()

    def test_maximum_bytes_exceeded(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body, max_size=103)
        request.set_client_time(1)

        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L))
        self.assertFalse(request.add_event(Event().set_message('eventTwo'), timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"}], threads: [], client_time: 1 }""")
        request.close()

    def test_maximum_bytes_exceeded_from_threads(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body, max_size=100)
        request.set_client_time(1)

        self.assertTrue(request.add_thread("t1", "name1"))
        self.assertFalse(request.add_thread("t2", "name2"))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [], threads: [{"id":"t1","name":"name1"}], client_time: 1 }""")

        request.close()

    def test_set_position(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L))

        request.set_position(position)
        self.assertTrue(request.add_event(Event().set_message('eventThree'), timestamp=3L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\neventThree},ts:"3"}], threads: [], client_time: 1 }""")

        request.close()

    def test_set_position_with_thread(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        request.add_thread('log1', 'Hi there')
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L))

        request.set_position(position)
        self.assertTrue(request.add_thread('log2', 'Log two'))
        self.assertTrue(request.add_event(Event().set_message('eventThree'), timestamp=3L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\neventThree},ts:"3"}], """
            """threads: [{"id":"log2","name":"Log two"}], client_time: 1 }""")

        request.close()

    def test_set_client_time(self):
        scalyr_client._set_last_timestamp( 0 )
        request = AddEventsRequest(self.__body)
        request.set_client_time(100)

        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            """, threads: [], client_time: 100 }""")

        request.set_client_time(2)
        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{attrs:{message:`s\x00\x00\x00\x08eventOne},ts:"1"},{attrs:{message:`s\x00\x00\x00\x08eventTwo},ts:"2"}]"""
            """, threads: [], client_time: 2 }""")
        request.close()

    def test_sequence_id_but_no_number( self ):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=1234))
        self.assertEquals(request.total_events, 1)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][0]

        self.assertFalse( 'si' in event )
        self.assertFalse( 'sn' in event )
        self.assertFalse( 'sd' in event )
        request.close()

    def test_sequence_number_but_no_id( self ):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_number=1234))
        self.assertEquals(request.total_events, 1)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][0]

        self.assertFalse( 'si' in event )
        self.assertFalse( 'sn' in event )
        self.assertFalse( 'sd' in event )
        request.close()

    def test_sequence_id_and_number( self ):
        expected_id = '1234'
        expected_number = 1234
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=expected_id, sequence_number=expected_number))
        self.assertEquals(request.total_events, 1)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][0]

        self.assertEquals( expected_id, event['si'] )
        self.assertEquals( expected_number, event['sn'] )
        self.assertFalse( 'sd' in event )
        request.close()

    def test_same_sequence_id( self ):
        expected_id = '1234'
        expected_number = 1234
        expected_delta = 1
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=expected_id, sequence_number=expected_number))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L, sequence_id=expected_id, sequence_number=expected_number+expected_delta))
        self.assertEquals(request.total_events, 2)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][1]

        self.assertFalse('si' in event)
        self.assertFalse('sn' in event)
        self.assertEquals( expected_delta, event['sd'] )
        request.close()

    def test_different_sequence_id( self ):
        first_id = '1234'
        second_id = '1235'
        first_number = 1234
        second_number = 1234
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=first_id, sequence_number=first_number))
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L, sequence_id=first_id, sequence_number=first_number+1))
        self.assertTrue(request.add_event(Event().set_message('eventThree'), timestamp=3L, sequence_id=second_id, sequence_number=second_number))
        self.assertEquals(request.total_events, 3)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][2]

        self.assertEquals( second_id, event['si'])
        self.assertEquals( second_number, event['sn'] )
        self.assertFalse('sd' in event)
        request.close()

    def test_exceeds_size_doesnt_effect_sequence( self ):
        first_id = '1234'
        second_id = '1235'
        first_number = 1234
        second_number = 4321
        expected_delta = 10
        request = AddEventsRequest(self.__body, max_size=180)
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=first_id, sequence_number=first_number))
        self.assertFalse(request.add_event(Event(attrs={'name': 'eventTwo', 'long': 'some really long text'}).set_message('eventTwo'), timestamp=2L, sequence_id=second_id, sequence_number=second_number))
        self.assertTrue(request.add_event(Event().set_message('eventThree'), timestamp=3L, sequence_id=first_id, sequence_number=first_number+expected_delta))
        self.assertEquals(request.total_events, 2)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][1]

        self.assertFalse('si' in event)
        self.assertEquals( expected_delta, event['sd'] )
        self.assertFalse('sn' in event)
        request.close()

    def test_set_position_resets_sequence_compression( self ):
        first_id = '1234'
        second_id = '1235'
        first_number = 1234
        second_number = 4321
        expected_delta = 10
        request = AddEventsRequest(self.__body )
        request.set_client_time(1)
        self.assertTrue(request.add_event(Event().set_message('eventOne'), timestamp=1L, sequence_id=first_id, sequence_number=first_number))
        position = request.position()
        self.assertTrue(request.add_event(Event().set_message('eventTwo'), timestamp=2L, sequence_id=first_id, sequence_number=first_number+expected_delta))
        request.set_position( position )
        self.assertTrue(request.add_event(Event().set_message('eventThree'), timestamp=3L, sequence_id=first_id, sequence_number=second_number))
        self.assertEquals(request.total_events, 2)

        json = json_lib.parse( request.get_payload() )
        event = json['events'][1]

        self.assertEquals( second_number, event['sn'] )
        self.assertFalse('sd' in event)
        request.close()

    def test_timing_data(self):
        request = AddEventsRequest(self.__body)
        request.increment_timing_data(foo=1, bar=2)
        request.increment_timing_data(foo=5)

        self.assertEquals(request.get_timing_data(), 'foo=6.0 bar=2.0')


class EventTest(ScalyrTestCase):
    def setUp(self):
        pass

    def test_all_fields(self):
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42L)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue())
        self.assertEquals(
            json_lib.JsonObject(thread="foo", ts="42", si="1", sn=2, sd=3,
                                attrs=json_lib.JsonObject(parser="bar", message="my_message", sample_rate=0.5)),
            json_lib.parse(output_buffer.getvalue()))

    def test_fast_path_fields(self):
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sequence_number_delta(3)
        x.set_timestamp(42L)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sd:3,ts:"42"}',
            output_buffer.getvalue())

    def test_individual_fields(self):
        # snd
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message('my_message')
        x.set_sequence_number_delta(3)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sd:3}',
            output_buffer.getvalue())

        # timestamp
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message('my_message')
        x.set_timestamp(42)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},ts:"42"}',
            output_buffer.getvalue())

        # sampling_rate
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message('my_message')
        x.set_sampling_rate(0.5)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5}}',
            output_buffer.getvalue())

        # sid
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message('my_message')
        x.set_sequence_id('hi')

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},si:"hi"}',
            output_buffer.getvalue())

        # seq num
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x.set_message('my_message')
        x.set_sequence_number(5)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message},sn:5}',
            output_buffer.getvalue())

    def test_only_message(self):
        x = Event()
        x.set_message("my_message")


        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{attrs:{message:`s\x00\x00\x00\nmy_message}}',
            output_buffer.getvalue())

    def test_no_thread_id(self):
        x = Event(attrs={"parser": "bar"})
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42L)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue())

    def test_no_attrs(self):
        x = Event(thread_id="biz")
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42L)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"biz", attrs:{message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue())

    def test_create_from_template(self):
        x = Event(thread_id='foo', attrs={"parser": "bar"})
        x = Event(base=x)
        x.set_message("my_message")
        x.set_sampling_rate(0.5)
        x.set_sequence_id(1)
        x.set_sequence_number(2)
        x.set_sequence_number_delta(3)
        x.set_timestamp(42L)

        output_buffer = StringIO()
        x.serialize(output_buffer)

        self.assertEquals(
            '{thread:"foo", attrs:{"parser":"bar",message:`s\x00\x00\x00\nmy_message,sample_rate:0.5},ts:"42",si:"1",sn:2,sd:3}',
            output_buffer.getvalue())


class EventSequencerTest(ScalyrTestCase):
    def setUp( self ):
        self.event_sequencer = EventSequencer()

    def test_sequence_id_but_no_number( self ):

        event = Event()
        self.event_sequencer.add_sequence_fields( event, '1234', None )
        self.assertIsNone( event.sequence_id  )
        self.assertIsNone( event.sequence_number)
        self.assertIsNone( event.sequence_number_delta )


    def test_sequence_number_but_no_id( self ):
        event = Event()
        self.event_sequencer.add_sequence_fields( event, None, 1234 )

        self.assertIsNone( event.sequence_id  )
        self.assertIsNone( event.sequence_number)
        self.assertIsNone( event.sequence_number_delta )

    def test_sequence_id_and_number( self ):
        expected_id = '1234'
        expected_number = 1234
        event = Event()
        self.event_sequencer.add_sequence_fields( event, expected_id, expected_number )

        self.assertEquals( expected_id, event.sequence_id )
        self.assertEquals( expected_number, event.sequence_number )
        self.assertIsNone( event.sequence_number_delta )

    def test_same_sequence_id( self ):
        expected_id = '1234'
        expected_number = 1234
        expected_delta = 1

        event = Event()
        self.event_sequencer.add_sequence_fields( event, expected_id, expected_number )

        event = Event()
        self.event_sequencer.add_sequence_fields( event, expected_id, expected_number + expected_delta )

        self.assertIsNone( event.sequence_id  )
        self.assertIsNone( event.sequence_number)
        self.assertEqual( expected_delta, event.sequence_number_delta )

    def test_different_sequence_id( self ):
        first_id = '1234'
        second_id = '1235'
        first_number = 1234
        second_number = 1234

        event = Event()
        self.event_sequencer.add_sequence_fields( event, first_id, first_number )

        event = Event()
        self.event_sequencer.add_sequence_fields( event, first_id, first_number+1 )

        event = Event()
        self.event_sequencer.add_sequence_fields( event, second_id, second_number )

        self.assertEquals( second_id, event.sequence_id )
        self.assertEquals( second_number, event.sequence_number )
        self.assertIsNone( event.sequence_number_delta )

    def test_memento( self ):
        first_id = '1234'
        second_id = '1235'
        first_number = 1234
        second_number = 1234

        event = Event()
        self.event_sequencer.add_sequence_fields( event, first_id, first_number )

        memento = self.event_sequencer.get_memento()

        event = Event()
        self.event_sequencer.add_sequence_fields( event, second_id, second_number )
        self.assertIsNotNone( event.sequence_id  )
        self.assertIsNotNone( event.sequence_number)
        self.assertIsNone( event.sequence_number_delta )

        self.event_sequencer.restore_from_memento( memento )

        event = Event()
        self.event_sequencer.add_sequence_fields( event, first_id, first_number + 1 )
        self.assertIsNone( event.sequence_id  )
        self.assertIsNone( event.sequence_number)
        self.assertIsNotNone( event.sequence_number_delta )

    def test_reset( self ):
        expected_id = '1234'
        expected_number = 1234
        expected_delta = 1

        event = Event()
        self.event_sequencer.add_sequence_fields( event, expected_id, expected_number )

        self.event_sequencer.reset()
        event = Event()
        self.event_sequencer.add_sequence_fields( event, expected_id, expected_number + expected_delta )

        self.assertEqual( expected_id, event.sequence_id )
        self.assertEqual( expected_number+expected_delta, event.sequence_number )
        self.assertIsNone( event.sequence_number_delta )

class PostFixBufferTest(ScalyrTestCase):

    def setUp(self):
        self.__format = '], threads: THREADS, client_time: TIMESTAMP }'

    def test_basic_case(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        test_buffer.add_thread_entry('log_5', 'histogram_builder')
        self.assertEquals(test_buffer.content(),
                          """], threads: [{"id":"log_5","name":"histogram_builder"}], client_time: 1 }""")

    def test_set_client_time(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)
        self.assertTrue(test_buffer.set_client_timestamp(433423))

        expected_length = test_buffer.length

        content = test_buffer.content(cache_size=False)

        self.assertEquals(content, '], threads: [], client_time: 433423 }')
        self.assertEquals(expected_length, len(content))

    def test_set_client_time_fail(self):
        test_buffer = PostFixBuffer(self.__format)
        self.assertTrue(test_buffer.set_client_timestamp(1, fail_if_buffer_exceeds=1000000))
        self.assertFalse(test_buffer.set_client_timestamp(433423, fail_if_buffer_exceeds=test_buffer.length+3))

        expected_length = test_buffer.length

        content = test_buffer.content(cache_size=False)

        self.assertEquals(content, '], threads: [], client_time: 1 }')
        self.assertEquals(expected_length, len(content))

    def test_add_thread(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        self.assertTrue(test_buffer.add_thread_entry('log_5', 'histogram_builder'))
        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertTrue(test_buffer.add_thread_entry('log_12', 'ok_builder'))
        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertTrue(test_buffer.add_thread_entry('log', 'histogram_builder_foo'))
        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertEquals(test_buffer.content(), """], threads: [{"id":"log_5","name":"histogram_builder"},"""
                                                 """{"id":"log_12","name":"ok_builder"},"""
                                                 """{"id":"log","name":"histogram_builder_foo"}], client_time: 1 }""")

    def test_add_thread_fail(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        self.assertTrue(test_buffer.add_thread_entry('log_5', 'histogram_builder', fail_if_buffer_exceeds=1000000))
        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertFalse(test_buffer.add_thread_entry('log_6', 'histogram', fail_if_buffer_exceeds=10))

        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertEquals(test_buffer.content(), """], threads: [{"id":"log_5","name":"histogram_builder"}], """
                                                 """client_time: 1 }""")

    def test_set_position(self):
        test_buffer = PostFixBuffer(self.__format)
        test_buffer.set_client_timestamp(1)

        self.assertTrue(test_buffer.add_thread_entry('log_5', 'histogram_builder'))

        position = test_buffer.position

        self.assertTrue(test_buffer.add_thread_entry('log_6', 'histogram2_builder'))

        test_buffer.set_position(position)

        self.assertEquals(test_buffer.length, len(test_buffer.content(cache_size=False)))

        self.assertEquals(test_buffer.content(), """], threads: [{"id":"log_5","name":"histogram_builder"}], """
                                                 """client_time: 1 }""")

class ClientSessionTest(ScalyrTestCase):

    def test_user_agent_callback(self):
        session = ScalyrClientSession("https://dummserver.com", "DUMMY API KEY", SCALYR_VERSION)

        def get_user_agent():
            return session._ScalyrClientSession__standard_headers['User-Agent']

        base_ua = get_user_agent()
        frags = ['frag1', 'frag2', 'frag3']
        session.augment_user_agent(frags)
        self.assertEquals(get_user_agent(), base_ua + ';' + ';'.join(frags))
