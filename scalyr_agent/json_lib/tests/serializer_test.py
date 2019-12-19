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
from __future__ import absolute_import
__author__ = "czerwin@scalyr.com"

from cStringIO import StringIO

from scalyr_agent.json_lib import serialize_as_length_prefixed_string

from scalyr_agent.test_base import ScalyrTestCase


class SerializeTests(ScalyrTestCase):
    def test_length_prefixed_strings(self):
        self.assertEquals(
            b"`s\x00\x00\x00\x0cHowdy folks!", self.serialize_string("Howdy folks!"),
        )

    def test_length_prefixed_strings_with_unicode(self):
        self.assertEquals(
            b"`s\x00\x00\x00\x10Howdy \xe8\x92\xb8 folks!",
            self.serialize_string(u"Howdy \u84b8 folks!"),
        )

    @staticmethod
    def serialize_string(input):
        result = StringIO()
        serialize_as_length_prefixed_string(input, result)
        return result.getvalue()
