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

from scalyr_agent.json_lib import serialize


class SerializeTests(unittest.TestCase):

    def test_numbers(self):
        self.assertEquals(self.write(1), '1')
        self.assertEquals(self.write(1.2), '1.2')
        self.assertEquals(self.write(133L), '133')

    def test_bool(self):
        self.assertEquals(self.write(True), 'true')
        self.assertEquals(self.write(False), 'false')

    def test_string(self):
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

        self.assertEquals(serialize('Escaped\xE2\x82\xAC', use_fast_encoding=True), '"Escaped\xe2\\u0082\xac"')
        self.assertEquals(serialize('Escaped\xE2\x82\xAC', use_fast_encoding=False), '"Escaped\\u20ac"')

    def test_dict(self):
        self.assertEquals(self.write({'hi': 5}), '{"hi":5}')
        self.assertEquals(self.write({'bye': 5, 'hi': True}), '{"bye":5,"hi":true}')
        self.assertEquals(self.write({'bye': 5, 'hi': {'foo': 5}}), '{"bye":5,"hi":{"foo":5}}')
        self.assertEquals(self.write({}), '{}')

    def test_array(self):
        self.assertEquals(self.write([1, 2, 5]), '[1,2,5]')
        self.assertEquals(self.write([]), '[]')

    def write(self, value):
        return serialize(value, use_fast_encoding=True)

    def __run_string_test_case(self, input_string, expected_result):
        self.assertEquals(serialize(input_string, use_fast_encoding=True), expected_result)
        self.assertEquals(serialize(input_string, use_fast_encoding=False), expected_result)