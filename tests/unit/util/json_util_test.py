#  -*- coding: utf-8 -*-
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

import os
import sys
import unittest
import importlib
import locale

import six
import mock
import pytest

from scalyr_agent import util
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

if six.PY3:
    reload = importlib.reload
    import orjson

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

    def test_64_bit_int(self):
        # NOTE: Latest version of orjson available for Python >= 3.6 can also serialize large
        # siigned and unsigned 64 bit ints
        if six.PY3:
            if sys.version_info >= (3, 6, 0):
                orjson.dumps(18446744073709551615)
            else:
                with self.assertRaises(orjson.JSONEncodeError):
                    orjson.dumps(18446744073709551615)

        # here we do the regular json tests to be sure that
        # we fall back to native json library in case of too bit integer.
        self.__test_encode_decode("18446744073709551615", 18446744073709551615)

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
                # a dict.
                # Our "rewind to last curly brace" logic in scalyr_agent/scalyr_client.py relies on
                # this behavior.
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


class UnicodeAndLocaleEncodingAndDecodingTestCase(ScalyrTestCase):
    def setUp(self):
        super(UnicodeAndLocaleEncodingAndDecodingTestCase, self).setUp()

        self.original_locale = locale.getlocale()

    def tearDown(self):
        super(UnicodeAndLocaleEncodingAndDecodingTestCase, self).tearDown()

        if self.original_locale:
            try:
                locale.setlocale(locale.LC_ALL, self.original_locale)
            except locale.Error:
                # unsupported localle setting error should not be fatal
                pass

        if "LC_ALL" in os.environ:
            del os.environ["LC_ALL"]

    def test_non_ascii_data_non_utf_locale_coding_default_json_lib(self):
        util.set_json_lib("json")
        original_data = "čććžšđ"

        # Default (UTF-8) locale
        result = util.json_encode(original_data)
        self.assertEqual(result, '"\\u010d\\u0107\\u0107\\u017e\\u0161\\u0111"')

        loaded = util.json_decode(result)
        self.assertEqual(loaded, original_data)

        # Non UTF-8 Locale
        os.environ["LC_ALL"] = "invalid"

        result = util.json_encode(original_data)
        self.assertEqual(result, '"\\u010d\\u0107\\u0107\\u017e\\u0161\\u0111"')

        loaded = util.json_decode(result)
        self.assertEqual(loaded, original_data)

    @skipIf(six.PY2, "Skipping under Python 2")
    def test_non_ascii_data_non_utf_locale_coding_orjson(self):
        util.set_json_lib("orjson")
        original_data = "čććžšđ"

        # Default (UTF-8) locale
        result = util.json_encode(original_data)
        self.assertEqual(result, '"%s"' % (original_data))

        loaded = util.json_decode(result)
        self.assertEqual(loaded, original_data)

        # Non UTF-8 Locale
        os.environ["LC_ALL"] = "invalid"

        result = util.json_encode(original_data)
        self.assertEqual(result, '"%s"' % (original_data))

        loaded = util.json_decode(result)
        self.assertEqual(loaded, original_data)

        # Invalid UTF-8, should fall back to standard json implementation
        original_data = "\ud800"
        result = util.json_encode(original_data)
        self.assertEqual(result, '"\\ud800"')

        loaded = util.json_decode('"\ud800"')
        self.assertEqual(loaded, original_data)


@pytest.mark.json_lib
class TestDefaultJsonLibrary(ScalyrTestCase):
    def setUp(self):
        super(TestDefaultJsonLibrary, self).setUp()
        # Save original modules so we can restore them after tests.
        self._original_modules = {}
        for name in ["orjson", "ujson", "json"]:
            if name in sys.modules:
                self._original_modules[name] = sys.modules[name]

    def tearDown(self):
        super(TestDefaultJsonLibrary, self).tearDown()
        # Restore original modules.
        for name, value in self._original_modules.items():
            sys.modules[name] = value

    @skipIf(six.PY2, "Skipping under Python 2")
    def test_correct_default_json_library_is_used_python3(self):

        json_lib_mock_mock = mock.Mock()

        json_lib_mock_mock.__spec__ = mock.Mock()
        sys.modules["orjson"] = json_lib_mock_mock

        self.assertEqual(util._determine_json_lib(), "orjson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = json_lib_mock_mock

        self.assertEqual(util._determine_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = None
        sys.modules["json"] = json_lib_mock_mock

        self.assertEqual(util._determine_json_lib(), "json")

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
