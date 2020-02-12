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

from scalyr_agent import util
from scalyr_agent.test_base import ScalyrTestCase

import six

JSON = 1
UJSON = 2


class EncodeDecodeTest(ScalyrTestCase):
    """This test ensures that the different json libraries can correctly encode/decode with the same results."""

    def _setlib(self, library):
        if library == JSON:
            util._set_json_lib("json")
        else:
            util._set_json_lib("ujson")

    def test_invalid_lib(self):
        self.assertRaises(
            ValueError, lambda: util._set_json_lib("BAD JSON LIBRARY NAME")
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
                self.assertEquals(six.ensure_text(text), text2)
                obj2 = util.json_decode(text2)
                text3 = util.json_encode(obj2)
                self.assertEquals(six.ensure_text(text), text3)
                obj3 = util.json_decode(text)
                self.assertEquals(obj3, obj)
            finally:
                util._set_json_lib(original_lib)

        if sys.version_info[:2] > (2, 4) and sys.version_info[:2] != (2, 6):
            __runtest(UJSON)
        if sys.version_info[:2] > (2, 5):
            __runtest(JSON)

        # do the same check but now with binary string.
        if isinstance(text, six.text_type):
            self.__test_encode_decode(text.encode("utf-8"), obj)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
