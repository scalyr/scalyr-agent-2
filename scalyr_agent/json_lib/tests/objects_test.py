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

from scalyr_agent.json_lib import JsonArray, JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.test_base import ScalyrTestCase


class JsonObjectTests(ScalyrTestCase):
    def test_constructor(self):
        x = JsonObject(foo=5, bar=True)
        self.assertEquals(x["foo"], 5)
        self.assertEquals(x.get("bar"), True)

    def test_get_bool(self):
        x = JsonObject(foo=True, bar=False)

        self.assertEquals(x.get_bool("foo"), True)
        self.assertEquals(x.get_bool("bar"), False)

        # Test conversion from int to bool
        x = JsonObject(foo=1, bar=0)
        self.assertEquals(x.get_bool("foo"), True)
        self.assertEquals(x.get_bool("bar"), False)

        # Test conversion from string to bool
        x = JsonObject(foo="ok", bar="f", barb="false", barc="")
        self.assertEquals(x.get_bool("foo"), True)
        self.assertEquals(x.get_bool("bar"), False)
        self.assertEquals(x.get_bool("barb"), False)
        self.assertEquals(x.get_bool("barc"), False)

        # Test that bad numbers raise an exception
        x = JsonObject(foo=5)
        self.assertRaises(JsonConversionException, x.get_bool, "foo")

        # Test the default value is returned if field is missing.
        self.assertEquals(x.get_bool("none", default_value=True), True)

        # Test returns none if missing.
        self.assertEquals(x.get_bool("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException, x.get_bool, "none")

    def test_get_int(self):
        x = JsonObject(foo=5)
        self.assertEquals(x.get_int("foo"), 5)

        x = JsonObject(foo=5L)
        self.assertEquals(x.get_int("foo"), 5)

        x = JsonObject(foo=5.21)
        self.assertEquals(x.get_int("foo"), 5)

        x = JsonObject(foo="5")
        self.assertEquals(x.get_int("foo"), 5)

        x = JsonObject(foo="5.2")
        self.assertEquals(x.get_int("foo"), 5)

        # Test that bad strings raise an exception
        x = JsonObject(foo="fhi3")
        self.assertRaises(JsonConversionException, x.get_int, "foo")

        # Test the default value is returned if field is missing.
        self.assertEquals(x.get_int("none", default_value=5), 5)

        # Test returns none if missing.
        self.assertEquals(x.get_int("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException, x.get_int, "none")

    def test_get_long(self):
        x = JsonObject(foo=5L)
        self.assertEquals(x.get_long("foo"), 5L)

        x = JsonObject(foo=5L)
        self.assertEquals(x.get_long("foo"), 5L)

        x = JsonObject(foo=5.21)
        self.assertEquals(x.get_long("foo"), 5L)

        x = JsonObject(foo="5")
        self.assertEquals(x.get_long("foo"), 5L)

        x = JsonObject(foo="5.2")
        self.assertEquals(x.get_long("foo"), 5L)

        # Test that bad strings raise an exception
        x = JsonObject(foo="fhi3")
        self.assertRaises(JsonConversionException, x.get_long, "foo")

        # Test the default value is returned if field is missing.
        self.assertEquals(x.get_long("none", default_value=5L), 5L)

        # Test returns none if missing.
        self.assertEquals(x.get_long("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException, x.get_long, "none")

    def test_get_float(self):
        x = JsonObject(foo=5.2, bar=True)
        self.assertEquals(x.get_float("foo"), 5.2)

        x = JsonObject(foo="5.2", bar=True)
        self.assertEquals(x.get_float("foo"), 5.2)

        # Test that bad strings raise an exception
        x = JsonObject(foo="fhi3")
        self.assertRaises(JsonConversionException, x.get_float, "foo")

        # Test the default value is returned if field is missing.
        self.assertEquals(x.get_long("none", default_value=5.2), 5.2)

        # Test returns none if missing.
        self.assertEquals(x.get_long("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException, x.get_long, "none")

    def test_get_string(self):
        x = JsonObject(foo="hi")
        self.assertEquals(x.get_string("foo"), "hi")

        x = JsonObject(foo=1)
        self.assertEquals(x.get_string("foo"), "1")

        # Test the default value is returned if field is missing.
        self.assertEquals(x.get_string("none", default_value="ok"), "ok")

        # Test returns none if missing.
        self.assertEquals(x.get_string("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException, x.get_string, "none")

    def test_get_json_object(self):
        x = JsonObject(foo=5, bar=True)
        y = JsonObject(bar=x)

        self.assertTrue(y.get_json_object("bar") == x)

        # Test the default value is returned if field is missing.
        self.assertTrue(x.get_json_object("none", default_value=x) == x)

        # Test returns none if missing.
        self.assertEquals(x.get_json_object("none", none_if_missing=True), None)

        # Raise an exception when field is missing.
        self.assertRaises(JsonMissingFieldException,
                          y.get_json_object, "none")

        # Raise an exception if field is not JsonObject
        self.assertRaises(JsonConversionException,
                          x.get_json_object, "foo")

    def test_get_or_create_json_object(self):
        x = JsonObject(foo=5, bar=True)
        y = JsonObject(bar=x)

        self.assertTrue(y.get_or_create_json_object("bar") == x)
        self.assertEquals(len(y.get_or_create_json_object("foo")), 0)

    def test_json_array_conversion(self):
        JsonObject(foo=5, bar=True)

    def test_equality(self):
        x = JsonObject(foo='a', bar=10)
        y = JsonObject(foo='a', bar=10)
        z = JsonObject(foo='a', bar=10, zar=True)

        self.assertEquals(x, y)
        self.assertNotEquals(x, z)
        self.assertNotEquals(y, z)

    def test_keys(self):
        x = JsonObject(foo='a', bar=10)

        keys = x.keys()
        self.assertEquals(len(keys), 2)
        self.assertTrue(keys[0] == 'foo' or keys[0] == 'bar')
        self.assertTrue(keys[1] == 'foo' or keys[1] == 'bar')

    def test_contains(self):
        x = JsonObject(foo='a', bar=10)
        self.assertTrue('foo' in x)
        self.assertFalse('baz' in x)

    def test_iter(self):
        x = JsonObject(foo='a', bar=10)

        keys = []
        for key in x:
            keys.append(key)

        self.assertEquals(len(keys), 2)
        self.assertTrue('foo' in keys)
        self.assertTrue('bar' in keys)


class JsonArrayTests(ScalyrTestCase):
    def test_constructor(self):
        x = JsonArray("hi", True)
        self.assertEquals(len(x), 2)
        self.assertEquals(x[0], "hi")
        self.assertEquals(x[1], True)

    def test_get_json_object(self):
        y = JsonObject(foo=True)
        x = JsonArray(y, "Not an object")
        self.assertEquals(len(x), 2)
        self.assertTrue(x.get_json_object(0) == y)
        self.assertRaises(JsonConversionException,
                          x.get_json_object, 1)

    def test_iter(self):
        y = JsonObject(foo=True)
        x = JsonArray(y, "Not an object")
        z = []

        for element in x:
            z.append(element)

        self.assertEquals(len(z), 2)
        self.assertTrue(x[0] == z[0])
        self.assertTrue(x[1] == z[1])

    def test_json_objects(self):
        y = JsonObject(foo=True)
        x = JsonArray(y)
        z = []

        for element in x.json_objects():
            z.append(element)

        self.assertEquals(len(z), 1)
        self.assertTrue(x[0] == z[0])

    def test_set_item(self):
        x = JsonArray('bye', 3)
        x[0] = 'hi'
        self.assertEquals(x[0], 'hi')

        self.assertRaises(IndexError, x.__setitem__, 5, 'foo')

    def test_equals(self):
        x = JsonArray(1, 2)
        y = JsonArray(1, 2)
        z = JsonArray(3, 4)

        self.assertEquals(x, y)
        self.assertNotEqual(x, z)
        self.assertNotEqual(y, z)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
