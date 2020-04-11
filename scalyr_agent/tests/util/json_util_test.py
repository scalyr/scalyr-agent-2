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
# author:  Edward Chee <echee@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "echee@scalyr.com"


import sys
import unittest
import importlib

import six
import mock

from scalyr_agent import util
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

if six.PY3:
    reload = importlib.reload

JSON = 1
UJSON = 2
ORJSON = 3


class EncodeDecodeTest(ScalyrTestCase):
    """This test ensures that the different json libraries can correctly encode/decode with the same results."""

    def _setlib(self, library):
        if library == JSON:
            util.set_json_lib("json")
        elif library == UJSON:
            util.set_json_lib("ujson")
        elif library == ORJSON:
            util.set_json_lib("orjson")
        else:
            raise ValueError("Invalid library name: %s" % (library))

    def test_invalid_lib(self):
        self.assertRaises(
            ValueError, lambda: util.set_json_lib("BAD JSON LIBRARY NAME")
        )

    def test_dict(self):
        self.__test_encode_decode('{"a":1,"b":2}', {"a": 1, "b": 2})

    def test_dict2(self):
        self.__test_encode_decode('{"a":1,"b":{"c":2}}', {"a": 1, "b": {"c": 2}})

    def test_str(self):
        self.__test_encode_decode(r'"a"', "a")

    def test_int(self):
        self.__test_encode_decode(r"1", 1)

    def test_negative_int(self):
        self.__test_encode_decode(r"-1", -1)

    def test_long(self):
        self.__test_encode_decode(r"1234567890123456789", 1234567890123456789)

    def test_negative_long(self):
        self.__test_encode_decode(r"-1234567890123456789", -1234567890123456789)

    def test_bool(self):
        self.__test_encode_decode(r"false", False)
        self.__test_encode_decode(r"true", True)

    def test_float(self):
        self.__test_encode_decode(r"1.0003", 1.0003)

    def test_negative_float(self):
        self.__test_encode_decode(r"-1.0003", -1.0003)

    def test_list(self):
        self.__test_encode_decode(r"[1,2,3]", [1, 2, 3])

    def test_list2(self):
        self.__test_encode_decode(r'[1,2,"a"]', [1, 2, "a"])

    def __test_encode_decode(self, text, obj):
        def __runtest(library):
            original_lib = util.get_json_lib()

            self._setlib(library)
            try:
                text2 = util.json_encode(obj)
                self.assertEquals(
                    sorted(six.ensure_text(text)),
                    sorted(text2),
                    "%s != %s" % (str(text), str(text2)),
                )
                obj2 = util.json_decode(text2)
                text3 = util.json_encode(obj2)
                self.assertEquals(
                    sorted(six.ensure_text(text)),
                    sorted(text3),
                    "%s != %s" % (str(text), str(text3)),
                )
                obj3 = util.json_decode(text)
                self.assertEquals(obj3, obj)

                # Sanity test to ensure curly brace is always the last character when serializing
                # a dict
                values = [
                    {},
                    {"a": "b"},
                    {"a": 1, "b": 2},
                ]

                for value in values:
                    result = util.json_encode(value)
                    self.assertEqual(result[-1], "}")
            finally:
                util.set_json_lib(original_lib)

        if sys.version_info[:2] > (2, 4) and sys.version_info[:2] != (2, 6):
            __runtest(UJSON)
        if sys.version_info[:2] > (2, 5):
            __runtest(JSON)
        if sys.version_info[:2] >= (3, 5):
            __runtest(ORJSON)

        # do the same check but now with binary string.
        if isinstance(text, six.text_type):
            self.__test_encode_decode(text.encode("utf-8"), obj)


class TestDefaultJsonLibrary(ScalyrTestCase):
    def tearDown(self):
        super(TestDefaultJsonLibrary, self).tearDown()

        for value in ["scalyr_agent.util", "orjson", "ujson", "json"]:
            if value in sys.modules:
                del sys.modules[value]

    @skipIf(six.PY2, "Skipping under Python 2")
    def test_correct_default_json_library_is_used_python3(self):
        sys.modules["orjson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "orjson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = None
        sys.modules["json"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "json")

    @skipIf(six.PY3, "Skipping under Python 3")
    def test_correct_default_json_library_is_used_python2(self):
        # NOTE: orjson is not available on Python 2 so we should not try and use it
        sys.modules["orjson"] = mock.Mock()
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = None
        sys.modules["json"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "json")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
