# Copyright 2017 Scalyr Inc.
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
# author: Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"


import unittest
from scalyr_agent.test_base import ScalyrTestCase


from scalyr_agent.builtin_monitors.syslog_monitor import SyslogRequestParser


class Handler(object):
    def __init__(self):
        self.values = []

    def handle(self, message):
        self.values.append(message)


class SyslogRequestParserTestCase(ScalyrTestCase):
    def test_framed_messages(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()

        parser.process(b"5 hello5 world", handler.handle)

        self.assertEqual(2, len(handler.values))
        self.assertEqual(b"hello", handler.values[0])
        self.assertEqual(b"world", handler.values[1])

    def test_framed_message_incomplete(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()

        parser.process(b"11 hello", handler.handle)

        self.assertEqual(0, len(handler.values))

        parser.process(b" world", handler.handle)

        self.assertEqual(1, len(handler.values))
        self.assertEqual(b"hello world", handler.values[0])

    def test_framed_message_multiple_incomplete(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()

        parser.process(b"11 hello", handler.handle)

        self.assertEqual(0, len(handler.values))
        parser.process(b" w", handler.handle)

        self.assertEqual(0, len(handler.values))
        parser.process(b"or", handler.handle)

        self.assertEqual(0, len(handler.values))
        parser.process(b"ld", handler.handle)

        self.assertEqual(1, len(handler.values))
        self.assertEqual(b"hello world", handler.values[0])

    def test_framed_message_invalid_frame_size(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()
        self.assertRaises(
            ValueError, lambda: parser.process(b"1a1 hello", handler.handle)
        )

    def test_framed_message_exceeds_max_size(self):
        parser = SyslogRequestParser(None, 11)
        handler = Handler()
        parser.process(b"23 hello world h", handler.handle)
        parser.process(b"10 lo world .", handler.handle)

        self.assertEqual(2, len(handler.values))
        self.assertEqual(b"23 hello world h", handler.values[0])
        self.assertEqual(b" 10 lo world .", handler.values[1])

    def test_unframed_messages(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()
        parser.process(b"hello\nworld\n", handler.handle)

        self.assertEqual(2, len(handler.values))
        self.assertEqual(b"hello", handler.values[0])
        self.assertEqual(b"world", handler.values[1])

    def test_unframed_messages_incomplete(self):
        parser = SyslogRequestParser(None, 32)
        handler = Handler()

        parser.process(b"hello", handler.handle)
        self.assertEqual(0, len(handler.values))

        parser.process(b" world\n", handler.handle)

        self.assertEqual(1, len(handler.values))
        self.assertEqual(b"hello world", handler.values[0])

    def test_unframed_message_exceeds_max_size(self):
        parser = SyslogRequestParser(None, 13)
        handler = Handler()

        parser.process(b"in my hand i have ", handler.handle)
        self.assertEqual(1, len(handler.values))
        self.assertEqual(b"in my hand i have ", handler.values[0])
        parser.process(b"100 dollars\n", handler.handle)
        self.assertEqual(2, len(handler.values))
        self.assertEqual(b"100 dollars", handler.values[1])


if __name__ == "__main__":
    unittest.main()
