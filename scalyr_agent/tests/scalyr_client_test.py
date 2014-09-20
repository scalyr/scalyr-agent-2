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

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, client_time: 1 }""")
        request.close()

    def test_multiple_calls_to_get_payload(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(1)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(request.get_payload(), request.get_payload())
        request.close()

    def test_maximum_bytes_exceeded(self):
        request = AddEventsRequest(self.__body, max_size=90)
        request.set_client_time(1)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertFalse(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(request.get_payload(),
                          """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"}], client_time: 1 }""")
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
            """{"token":"fakeToken", events: [{"name":"eventThree","ts":"3"}], client_time: 1 }""")

        request.close()

    def test_set_client_time(self):
        request = AddEventsRequest(self.__body)
        request.set_client_time(100)

        self.assertTrue(request.add_event({'name': 'eventOne'}, timestamp=1L))
        self.assertTrue(request.add_event({'name': 'eventTwo'}, timestamp=2L))

        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, client_time: 100 }""")

        request.set_client_time(2)
        self.assertEquals(
            request.get_payload(),
            """{"token":"fakeToken", events: [{"name":"eventOne","ts":"1"},{"name":"eventTwo","ts":"2"}]"""
            """, client_time: 2 }""")
        request.close()