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

__author__ = 'echee@scalyr.com'

import json
import ujson
import unittest

from functools import partial

from scalyr_agent import util
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray
from scalyr_agent.test_base import ScalyrTestCase

JSON = 1
UJSON = 2
FALLBACK = 3
ALL_JSON_LIBS = [FALLBACK]
ALL_JSON_LIBS_AS_TUPLES = [(lib,) for lib in ALL_JSON_LIBS]

class EncodeDecodeTest(ScalyrTestCase):
    """This test ensures that JsonObject and JsonArray can be correctly encoded/decoded with different JSON libraries"""

    def _setlib(self, library):
        if library == JSON:
            util._json_encode = partial(json.dumps, separators=(',', ':'))
            util._json_decode = json.loads
        elif library == UJSON:
            util._json_encode = ujson.dumps
            util._json_decode = ujson.loads
        else:
            util._json_encode = util._fallback_json_encode
            util._json_decode = util._fallback_json_decode

    def test_dict(self):
        self.__test_encode_decode('{"a":1,"b":2}', {u'a': 1, u'b': 2})

    def test_dict2(self):
        self.__test_encode_decode('{"a":1,"b":{"c":2}}', {u'a': 1, u'b': {u'c': 2}})

    # def test_str(self):
    #     self.__test_encode_decode(r'"a"', u'a')
    #
    # def test_int(self):
    #     self.__test_encode_decode(r'1', 1)
    #
    # def test_bool(self):
    #     self.__test_encode_decode(r'false', False)
    #     self.__test_encode_decode(r'true', True)
    #
    # def test_float(self):
    #     self.__test_encode_decode(r'1.0003', 1.0003)
    #
    # def test_list(self):
    #     self.__test_encode_decode(r'[1,2,3]', [1, 2, 3])
    #
    # def test_list2(self):
    #     self.__test_encode_decode(r'[1,2,"a"]', [1, 2, u'a'])
    #
    # def test_dict(self):
    #     self.__test_encode_decode(r'{"a":1,"b":2}', JsonObject({u'a': 1, u'b': 2}))
    #
    # def test_dict_nested_dict(self):
    #     self.__test_encode_decode(r'{"a":{"b":{"c":3}}}', JsonObject({u'a': JsonObject({u'b': JsonObject({u'c': 3})})}))
    #
    # def test_dict_nested_list(self):
    #     self.__test_encode_decode(r'{"a":[1,2,3]}', JsonObject({u'a': JsonArray(1, 2, 3)}))
    #
    # def test_dict_nested_list2(self):
    #     self.__test_encode_decode(r'{"a":[1,2,3,[1,2,3]]}', JsonObject({u'a': JsonArray(1, 2, 3, JsonArray(1, 2, 3))}))

    def __test_encode_decode(self, text, obj):
        def __runtest(library):
            self._setlib(library)
            text2 = util.json_encode(obj)
            self.assertEquals(text, text2)

            obj2 = util.json_decode(text2)
            self.assertEquals(type(obj2), type(obj))
            self.assertEquals(obj2, obj)

            text3 = util.json_encode(obj2)
            self.assertEquals(text, text3)

        __runtest(JSON)
        __runtest(UJSON)
        # __runtest(FALLBACK)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
