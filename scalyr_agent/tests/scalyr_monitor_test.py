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


from scalyr_agent.json_lib.objects import JsonArray, JsonObject, ArrayOfStrings
from scalyr_agent.scalyr_monitor import (
    MonitorConfig,
    BadMonitorConfiguration,
    define_config_option,
)
from scalyr_agent.test_base import ScalyrTestCase

import scalyr_agent.util as scalyr_util

import six


class MonitorConfigTest(ScalyrTestCase):
    def test_base(self):
        test_array = ["a", 1, False]
        test_obj = {"a": 100, "b": 200}
        config = MonitorConfig(
            {
                "int": 1,
                "bool": True,
                "string": "hi",
                "unicode": "bye",
                "float": 1.4,
                "long": 1,
                "JsonArray": JsonArray(*test_array),
                "JsonObject": JsonObject(**test_obj),
            }
        )

        self.assertEquals(len(config), 8)
        self.assertTrue("int" in config)
        self.assertFalse("foo" in config)

        self.assertEquals(config["int"], 1)
        self.assertEquals(config["bool"], True)
        self.assertEquals(config["string"], "hi")
        self.assertEquals(config["unicode"], "bye")
        self.assertEquals(config["float"], 1.4)
        self.assertEquals(config["long"], 1)
        self.assertEquals(config["JsonArray"], JsonArray(*test_array))
        self.assertEquals(config["JsonObject"], JsonObject(**test_obj))

        count = 0
        for _ in config:
            count += 1
        self.assertEquals(count, 8)

    def test_int_conversion(self):
        self.assertEquals(self.get(1, convert_to=int), 1)
        self.assertEquals(self.get("12", convert_to=int), 12)
        self.assertEquals(self.get("13", convert_to=int), 13)

        self.assertRaises(BadMonitorConfiguration, self.get, 2.0, convert_to=int)
        self.assertRaises(BadMonitorConfiguration, self.get, True, convert_to=int)
        self.assertRaises(BadMonitorConfiguration, self.get, "12a", convert_to=int)

    def test_str_conversion(self):
        self.assertEquals(self.get(1, convert_to=six.text_type), "1")
        self.assertEquals(self.get("ah", convert_to=six.text_type), "ah")
        self.assertEquals(self.get(False, convert_to=six.text_type), "False")
        self.assertEquals(self.get(1.3, convert_to=six.text_type), "1.3")
        self.assertEquals(self.get(1, convert_to=six.text_type), "1")

        test_array = ["a", "b", "c"]

        # str -> ArrayOfStrings (must support different variations)
        arr = ArrayOfStrings(test_array)
        self.assertEquals(self.get("a,b,c", convert_to=ArrayOfStrings), arr)
        self.assertEquals(self.get("a,b,  c", convert_to=ArrayOfStrings), arr)
        self.assertEquals(self.get('"a", "b", "c"', convert_to=ArrayOfStrings), arr)
        self.assertEquals(self.get("'a', 'b', 'c'", convert_to=ArrayOfStrings), arr)
        self.assertEquals(self.get("[a, b, c]", convert_to=ArrayOfStrings), arr)
        self.assertEquals(self.get("['a', \"b\", c]", convert_to=ArrayOfStrings), arr)

        # str -> JsonArray
        self.assertEquals(
            self.get(scalyr_util.json_encode(test_array), convert_to=JsonArray),
            JsonArray(*test_array),
        )
        self.assertRaises(
            BadMonitorConfiguration,
            # single quotes are invalid JSON
            lambda: self.assertEquals(
                self.get(six.text_type(test_array), convert_to=JsonArray),
                JsonArray(*test_array),
            ),
        )

        # str -> JsonObject
        test_obj = {"a": 1, "b": "two", "c": [1, 2, 3]}
        self.assertEquals(
            self.get(scalyr_util.json_encode(test_obj), convert_to=JsonObject),
            scalyr_util.json_scalyr_config_decode(scalyr_util.json_encode(test_obj)),
        )

    def test_unicode_conversion(self):
        self.assertEquals(self.get(1, convert_to=six.text_type), "1")
        self.assertEquals(self.get("ah", convert_to=six.text_type), "ah")
        self.assertEquals(self.get(False, convert_to=six.text_type), "False")
        self.assertEquals(self.get(1.3, convert_to=six.text_type), "1.3")
        self.assertEquals(self.get(1, convert_to=six.text_type), "1")

    def test_long_conversion(self):
        self.assertEquals(self.get(2, convert_to=int), 2)
        self.assertEquals(self.get("3", convert_to=int), 3)
        self.assertEquals(self.get(1, convert_to=int), 1)
        self.assertRaises(BadMonitorConfiguration, self.get, True, convert_to=int)
        self.assertRaises(BadMonitorConfiguration, self.get, "12a", convert_to=int)

    def test_float_conversion(self):
        self.assertEquals(self.get(2, convert_to=float), 2.0)
        self.assertEquals(self.get("3.2", convert_to=float), 3.2)
        self.assertEquals(self.get(1, convert_to=float), 1.0)
        self.assertRaises(BadMonitorConfiguration, self.get, True, convert_to=float)
        self.assertRaises(BadMonitorConfiguration, self.get, "12a", convert_to=float)

    def test_bool_conversion(self):
        self.assertEquals(self.get(True, convert_to=bool), True)
        self.assertEquals(self.get(False, convert_to=bool), False)
        self.assertEquals(self.get("true", convert_to=bool), True)
        self.assertEquals(self.get("false", convert_to=bool), False)

        self.assertRaises(BadMonitorConfiguration, self.get, 1, convert_to=bool)
        self.assertRaises(BadMonitorConfiguration, self.get, 2.1, convert_to=bool)
        self.assertRaises(BadMonitorConfiguration, self.get, 3, convert_to=bool)

    def test_list_conversion(self):
        # list -> JsonArray supported
        test_array = ["a", 1, False]
        json_arr = JsonArray(*test_array)
        self.assertEquals(
            self.get(list(json_arr), convert_to=JsonArray), JsonArray(*test_array),
        )

        # list -> ArrayOfStrings not supported
        test_array = ["a", "b", "c"]
        self.assertEquals(
            self.get(test_array, convert_to=ArrayOfStrings), ArrayOfStrings(test_array)
        )

    def test_jsonarray_conversion(self):
        # JsonArray -> list not supported
        test_array = ["a", "b", "c"]
        json_arr = JsonArray(*test_array)
        self.assertRaises(
            BadMonitorConfiguration, lambda: self.get(json_arr, convert_to=list)
        )

        # JsonArray -> ArrayOfStrings supported
        test_array = ["a", "b", "c"]
        json_arr = JsonArray(*test_array)
        self.assertEquals(
            self.get(json_arr, convert_to=ArrayOfStrings), ArrayOfStrings(test_array)
        )

        # JsonArray -> invalid ArrayOfStrings
        test_array = ["a", "b", 3]
        json_arr = JsonArray(*test_array)
        self.assertRaises(
            BadMonitorConfiguration,
            lambda: self.get(json_arr, convert_to=ArrayOfStrings),
        )

    def test_arrayofstrings_conversion(self):
        # JsonArray -> list not supported
        test_array = ["a", "b", "c"]
        json_arr = ArrayOfStrings(test_array)
        self.assertRaises(
            BadMonitorConfiguration, lambda: self.get(json_arr, convert_to=list)
        )

        # ArrayOfStrings -> JsonArray supported
        test_array = ["a", "b", "c"]
        json_arr = JsonArray(*test_array)
        self.assertEquals(
            self.get(json_arr, convert_to=JsonArray), JsonArray(*test_array)
        )

    def test_required_field(self):
        config = MonitorConfig({"foo": 10})

        self.assertEquals(config.get("foo", required_field=True), 10)
        self.assertRaises(
            BadMonitorConfiguration, config.get, "fo", required_field=True
        )

    def test_max_value(self):
        self.assertRaises(BadMonitorConfiguration, self.get, 5, max_value=4)
        self.assertEquals(self.get(2, max_value=3), 2)

    def test_min_value(self):
        self.assertRaises(BadMonitorConfiguration, self.get, 5, min_value=6)
        self.assertEquals(self.get(4, min_value=3), 4)

    def test_default_value(self):
        config = MonitorConfig({"foo": 10})

        self.assertEquals(config.get("foo", default=20), 10)
        self.assertEquals(config.get("fee", default=20), 20)

    def test_define_config_option(self):
        define_config_option(
            "foo", "a", "Description", required_option=True, convert_to=int
        )
        self.assertRaises(
            BadMonitorConfiguration, MonitorConfig, {"b": 1}, monitor_module="foo"
        )

        config = MonitorConfig({"a": "5"}, monitor_module="foo")
        self.assertEquals(config.get("a"), 5)

        define_config_option(
            "foo",
            "b",
            "Description",
            min_value=5,
            max_value=10,
            default=7,
            convert_to=int,
        )

        config = MonitorConfig({"a": 5}, monitor_module="foo")
        self.assertEquals(config.get("b"), 7)

        self.assertRaises(
            BadMonitorConfiguration,
            MonitorConfig,
            {"a": 5, "b": 1},
            monitor_module="foo",
        )
        self.assertRaises(
            BadMonitorConfiguration,
            MonitorConfig,
            {"a": 5, "b": 11},
            monitor_module="foo",
        )

        # Test case where no value in config for option with no default value should result in no value in
        # MonitorConfig object
        define_config_option(
            "foo", "c", "Description", min_value=5, max_value=10, convert_to=int
        )
        config = MonitorConfig({"a": 5}, monitor_module="foo")
        self.assertTrue("c" not in config)

    def test_list_of_strings(self):
        define_config_option(
            "foo", "some_param", "A list of strings", default=["a", "b", "c", "d"]
        )
        self.assertEquals(self.get(["x", "y", "z"], convert_to=None), ["x", "y", "z"])
        self.assertRaises(
            Exception,
            lambda: self.get("['x', 'y', 'z']", convert_to=list),
            ["x", "y", "z"],
        )

    def get(
        self,
        original_value,
        convert_to=None,
        required_field=False,
        max_value=None,
        min_value=None,
    ):
        config = MonitorConfig({"foo": original_value})
        return config.get(
            "foo",
            convert_to=convert_to,
            required_field=required_field,
            max_value=max_value,
            min_value=min_value,
        )
