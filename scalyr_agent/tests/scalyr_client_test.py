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

from scalyr_agent.scalyr_client import AddEventsRequest


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