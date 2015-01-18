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

import unittest

from scalyr_agent.scalyr_client import AddEventsRequest, PostFixBuffer


class AddEventsRequestTest(unittest.TestCase):

    def setUp(self):
        self.__body = {'token': 'fakeToken'}

    def test_basic_case(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, threads: [], client_time: 1 }""")
        self.assertEquals(request.total_events, 2)
        request.close()

    def test_multiple_calls_to_get_payload(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(request.get_payload(), request.get_payload())
        request.close()

    def test_add_thread(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertEquals(request.total_events, 0)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_thread('t1', 'n1'))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))
        self.assertTrue(request.add_thread('t2', 'n2'))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, threads: [{"id":"t1","name":"n1"},{"id":"t2","name":"n2"}], client_time: 1 }""")

        self.assertEquals(request.total_events, 2)
        request.close()

    def test_maximum_bytes_exceeded(self):
        request = AddEventsRequest(self.__body, max_size=103)
        request.set_client_time(1)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertFalse(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"}], threads: [], client_time: 1 }""")
        request.close()

    def test_maximum_bytes_exceeded_from_threads(self):
        request = AddEventsRequest(self.__body, max_size=100)
        request.set_client_time(1)

        self.assertTrue(request.add_thread("t1", "name1"))
        self.assertFalse(request.add_thread("t2", "name2"))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [], threads: [{"id":"t1","name":"name1"}], client_time: 1 }""")

        request.close()

    def test_set_position(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        request.set_position(position)
        self.assertTrue(request.add_event({'name': 'eventThree'}, timestamp=3L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventThree","ts":"3"}], threads: [], client_time: 1 }""")

        request.close()

    def test_set_position_with_thread(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)
        position = request.position()
        request.add_thread('log1', 'Hi there')
        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        request.set_position(position)
        self.assertTrue(request.add_thread('log2', 'Log two'))
        self.assertTrue(request.add_event({'name': 'eventThree'}, timestamp=3L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventThree","ts":"3"}], """
            """threads: [{"id":"log2","name":"Log two"}], client_time: 1 }""")

        request.close()

    def test_set_client_time(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(100)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, threads: [], client_time: 100 }""")

        request.set_client_time(2)
        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, threads: [], client_time: 2 }""")
        request.close()


class PostFixBufferTest(unittest.TestCase):

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
