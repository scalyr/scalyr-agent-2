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

from scalyr_agent.json_lib.parser import ByteScanner, JsonParser, JsonParseException

from scalyr_agent.test_base import ScalyrTestCase


class ByteScannerTests(ScalyrTestCase):
    def test_constructor(self):
        x = ByteScanner("Hi there")

        self.assertEquals(x.position, 0)

    def test_read_ubyte(self):
        x = ByteScanner("Hi \n")

        self.assertEquals(x.read_ubyte(), "H")
        self.assertEquals(x.read_ubyte(), "i")
        self.assertEquals(x.read_ubyte(), " ")
        self.assertEquals(x.read_ubyte(), "\n")
        self.assertRaises(IndexError, x.read_ubyte)

    def test_read_ubytes(self):
        x = ByteScanner("Hi there\n")

        self.assertEquals(x.read_ubytes(2), "Hi")
        self.assertEquals(x.read_ubytes(4), " the")
        self.assertRaises(IndexError, x.read_ubytes, 10)

    def test_properties(self):
        x = ByteScanner("Hi \n")
        
        self.assertEquals(x.position, 0)
        self.assertFalse(x.at_end)
        self.assertEquals(x.bytes_remaining, 4)

        x.read_ubyte()
        self.assertEquals(x.position, 1)
        self.assertFalse(x.at_end)
        self.assertEquals(x.bytes_remaining, 3)

        x.read_ubyte()
        self.assertEquals(x.position, 2)
        self.assertFalse(x.at_end)
        self.assertEquals(x.bytes_remaining, 2)

        x.read_ubyte()
        self.assertEquals(x.position, 3)
        self.assertFalse(x.at_end)
        self.assertEquals(x.bytes_remaining, 1)

        x.read_ubyte()
        self.assertEquals(x.position, 4)
        self.assertTrue(x.at_end)
        self.assertEquals(x.bytes_remaining, 0)

    def test_peek_next_ubyte(self):
        x = ByteScanner("Hi \n")

        x.read_ubyte()
        x.read_ubyte()

        self.assertEquals(x.peek_next_ubyte(), " ")
        self.assertEquals(x.peek_next_ubyte(1), "\n")
        self.assertEquals(x.peek_next_ubyte(2, none_if_bad_index=True), None)
        self.assertRaises(IndexError, x.peek_next_ubyte, 2)

    def test_peek_next_ubyte_with_negative(self):
        x = ByteScanner("Hi \n")

        x.read_ubyte()
        x.read_ubyte()

        self.assertEquals(x.peek_next_ubyte(-1), "i")
        self.assertEquals(x.peek_next_ubyte(-2), "H")
        self.assertEquals(x.peek_next_ubyte(-3, none_if_bad_index=True), None)
        self.assertRaises(IndexError, x.peek_next_ubyte, (-3))

    def test_line_number_for_offset(self):
        x = ByteScanner("Hi there\nAnother line\nOne more")

        self.assertEquals(x.line_number_for_offset(4), 1)
        self.assertEquals(x.line_number_for_offset(9), 2)
        self.assertEquals(x.line_number_for_offset(23), 3)

        x = ByteScanner("Hi there\rAnother line")

        self.assertEquals(x.line_number_for_offset(4), 1)
        self.assertEquals(x.line_number_for_offset(9), 2)

        x = ByteScanner("Hi there\r\nAnother line")

        self.assertEquals(x.line_number_for_offset(4), 1)
        self.assertEquals(x.line_number_for_offset(10), 2)

        self.assertRaises(IndexError, x.line_number_for_offset, 25)

    def test_line_number_for_offset_with_negative_offset(self):
        x = ByteScanner("Hi there\nAnother line\nOne more")
        #                 01234567 8901234567890 12345678
        # Advance to the 'n' in One.
        for i in range(23):
            x.read_ubyte()

        self.assertEquals(x.line_number_for_offset(-2), 2)
        self.assertEquals(x.line_number_for_offset(-1), 3)
        self.assertEquals(x.line_number_for_offset(-20), 1)

        self.assertRaises(IndexError, x.line_number_for_offset, (-25))


class JsonParserTests(ScalyrTestCase):
    def test_parsing_numbers(self):
        x = JsonParser.parse("123")
        self.assertEquals(x, 123)

        x = JsonParser.parse("-10")
        self.assertEquals(x, -10)

        x = JsonParser.parse("-10.5")
        self.assertEquals(x, -10.5)

        x = JsonParser.parse("12345678901234567890")
        self.assertEquals(x, 12345678901234567890L)

        self.assertRaises(JsonParseException, JsonParser.parse, "1..e")

    def test_parsing_strings(self):
        x = JsonParser.parse("\"Hi there\"")
        self.assertEquals(x, "Hi there")

        x = JsonParser.parse("\"Hi there\" \n + \" Bye there\"")
        self.assertEquals(x, "Hi there Bye there")

        x = JsonParser.parse("\"Hi there\\n\"")
        self.assertEquals(x, "Hi there\n")

        x = JsonParser.parse("\"Hi there\\ua000\"")
        self.assertEquals(x, u"Hi there\ua000")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "\"Hi there")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "\"Hi there \n ok bye \"")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "\"Hi there \\")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "\"Hi there\" + Hi")

    def test_parsing_length_prefixed_strings(self):
        x = JsonParser.parse('`s\x00\x00\x00\x0cHowdy folks!')
        self.assertEquals('Howdy folks!', x)

    def test_triple_quoted_strings(self):
        x = JsonParser.parse('"""Howdy\n"folks"!"""')
        self.assertEquals('Howdy\n"folks"!', x)

    def test_parsing_boolean(self):
        x = JsonParser.parse("true")
        self.assertEquals(x, True)

        x = JsonParser.parse("false")
        self.assertEquals(x, False)

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "tuto")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "foo")

    def test_parsing_null(self):
        x = JsonParser.parse("null")
        self.assertEquals(x, None)

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "nill")

    def test_parsing_comment(self):
        x = JsonParser.parse(" // Hi there\n  45")
        self.assertEquals(x, 45)

        x = JsonParser.parse(" /* Hi there */ 45")
        self.assertEquals(x, 45)

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "/* Unterminated comment")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "/ Hi there")

    def test_parsing_array(self):
        x = JsonParser.parse("[1, 2, 3]")
        self.assertEquals(len(x), 3)
        self.assertEquals(x[0], 1)
        self.assertEquals(x[1], 2)
        self.assertEquals(x[2], 3)

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "[ 1, 2,")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "[ 1, 2 3]")

        x = JsonParser.parse("[1, 2\n 3]")
        self.assertEquals(len(x), 3)

    def test_parsing_object(self):
        x = JsonParser.parse("{ a: 5}")
        self.assertEquals(len(x), 1)
        self.assertEquals(x.get("a"), 5)

        x = JsonParser.parse("{ a: 5, b:3, c:true}")
        self.assertEquals(len(x), 3)
        self.assertEquals(x.get("a"), 5)
        self.assertEquals(x.get("b"), 3)
        self.assertEquals(x.get("c"), True)

        x = JsonParser.parse("{ \"a\": 5}")
        self.assertEquals(len(x), 1)
        self.assertEquals(x.get("a"), 5)

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "{ a 5}")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "{ a: 5")

        self.assertRaises(JsonParseException, JsonParser.parse, 
                          "{ a")

    def test_inferring_missing_comma(self):
        x = JsonParser.parse("""{
                                   a: 5
                                   b: 7
                                 }""")
        self.assertEquals(len(x), 2)
        self.assertEquals(x.get("a"), 5)
        self.assertEquals(x.get("b"), 7)


def main():
    unittest.main()

if __name__ == '__main__':
    main()