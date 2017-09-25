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
# author:  Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import unittest
from scalyr_agent.json_lib import serialize, serialize_as_length_prefixed_string

from scalyr_agent.test_base import ScalyrTestCase


class SerializeTests(ScalyrTestCase):
    def test_numbers(self):
        self.assertEquals(self.write(1), '1')
        self.assertEquals(self.write(1.2), '1.2')
        self.assertEquals(self.write(133L), '133')

    def test_bool(self):
        self.assertEquals(self.write(True), 'true')
        self.assertEquals(self.write(False), 'false')

    def test_4byte_utf8_fast(self):
        actual = '\xF0\xAA\x9A\xA5'
        expected_fast = '"\xf0\xaa\\u009a\xa5"'
        self.assertEquals(serialize(actual, use_fast_encoding=True), expected_fast)

        actual = '\xF0\x9F\x98\xA2'
        expected_fast = '"\xf0\\u009f\\u0098\xa2"'
        self.assertEquals(serialize(actual, use_fast_encoding=True), expected_fast)

    @unittest.skip("@czerwin to take a look why slow encoding is not working.")
    def test_4byte_utf8_slow(self):
        actual = '\xF0\xAA\x9A\xA5'
        expected_slow = '"\\U0002a6a5"'
        self.assertEquals(serialize(actual, use_fast_encoding=False), expected_slow)

        actual = '\xF0\x9F\x98\xA2'
        expected_slow = '"\\U0001f622"'
        self.assertEquals(serialize(actual, use_fast_encoding=False), expected_slow)

    def test_string_fast(self):
        self.__run_string_test_case('Hi there', '"Hi there"')
        self.__run_string_test_case('Hi there\n', '"Hi there\\n"')
        self.__run_string_test_case('Hi there\b', '"Hi there\\b"')
        self.__run_string_test_case('Hi there\f', '"Hi there\\f"')
        self.__run_string_test_case('Hi there\r', '"Hi there\\r"')
        self.__run_string_test_case('Hi there\t', '"Hi there\\t"')
        self.__run_string_test_case('Hi there\"', '"Hi there\\""')
        self.__run_string_test_case('Hi there\\', '"Hi there\\\\"')

        self.__run_string_test_case('Escaped\5', '"Escaped\\u0005"')
        self.__run_string_test_case('Escaped\17', '"Escaped\\u000f"')
        self.__run_string_test_case('Escaped\177', '"Escaped\\u007f"')
        self.__run_string_test_case('Escaped\177', '"Escaped\\u007f"')
        self.__run_string_test_case(u'\u2192', '"\\u2192"')

        self.assertEquals(serialize('Escaped\xE2\x82\xAC', use_fast_encoding=True), '"Escaped\xe2\\u0082\xac"')

    @unittest.skip("@czerwin to take a look why slow encoding is not working.")
    def test_string_slow(self):
        self.__run_string_test_case('Hi there', '"Hi there"')
        self.__run_string_test_case('Hi there\n', '"Hi there\\n"')
        self.__run_string_test_case('Hi there\b', '"Hi there\\b"')
        self.__run_string_test_case('Hi there\f', '"Hi there\\f"')
        self.__run_string_test_case('Hi there\r', '"Hi there\\r"')
        self.__run_string_test_case('Hi there\t', '"Hi there\\t"')
        self.__run_string_test_case('Hi there\"', '"Hi there\\""')
        self.__run_string_test_case('Hi there\\', '"Hi there\\\\"')

        self.__run_string_test_case('Escaped\5', '"Escaped\\u0005"')
        self.__run_string_test_case('Escaped\17', '"Escaped\\u000f"')
        self.__run_string_test_case('Escaped\177', '"Escaped\\u007f"')
        self.__run_string_test_case('Escaped\177', '"Escaped\\u007f"')
        self.__run_string_test_case(u'\u2192', '"\\u2192"')

        self.assertEquals(serialize('Escaped\xE2\x82\xAC', use_fast_encoding=False), '"Escaped\\u20ac"')

    def test_dict(self):
        self.assertEquals(self.write({'hi': 5}), '{"hi":5}')
        self.assertEquals(self.write({'bye': 5, 'hi': True}), '{"bye":5,"hi":true}')
        self.assertEquals(self.write({'bye': 5, 'hi': {'foo': 5}}), '{"bye":5,"hi":{"foo":5}}')
        self.assertEquals(self.write({}), '{}')

    def test_array(self):
        self.assertEquals(self.write([1, 2, 5]), '[1,2,5]')
        self.assertEquals(self.write([]), '[]')

    def test_length_prefixed_strings(self):
        self.assertEquals('`s\x00\x00\x00\x0cHowdy folks!', serialize('Howdy folks!', use_length_prefix_string=True))

    def test_length_prefixed_strings_with_unicode(self):
        self.assertEquals('`s\x00\x00\x00\x10Howdy \xe8\x92\xb8 folks!', serialize(u'Howdy \u84b8 folks!',
                                                                                   use_length_prefix_string=True))

    def write(self, value):
        return serialize(value, use_fast_encoding=True)

    def __run_string_test_case(self, input_string, expected_result):
        self.assertEquals(serialize(input_string, use_fast_encoding=True), expected_result)
        self.assertEquals(serialize(input_string, use_fast_encoding=False), expected_result)
