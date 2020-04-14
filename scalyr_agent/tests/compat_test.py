# Copyright 2014-2020 Scalyr Inc.
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

"""
Module which tests the compat.py functionality.
"""

from __future__ import unicode_literals
from __future__ import absolute_import


import os
import unittest

import six
from scalyr_agent.compat import os_environ_unicode


class EnvironUnicode(unittest.TestCase):
    TEST_VAR = "TEST_VAR_ENVIRON_UNICODE"

    def test_environ_get(self):
        os.environ[EnvironUnicode.TEST_VAR] = six.ensure_binary("Test string")
        self.assertEqual(
            os_environ_unicode.get(EnvironUnicode.TEST_VAR),
            six.text_type("Test string"),
        )
        self.assertEqual(
            os_environ_unicode[EnvironUnicode.TEST_VAR], six.text_type("Test string")
        )

    def test_environ_set(self):
        os_environ_unicode[EnvironUnicode.TEST_VAR] = six.ensure_binary(
            "Test two string"
        )
        self.assertEqual(
            os_environ_unicode.get(EnvironUnicode.TEST_VAR),
            six.text_type("Test two string"),
        )

    def test_environ_pop(self):
        os_environ_unicode[EnvironUnicode.TEST_VAR] = six.ensure_binary(
            "Test four string"
        )
        value = os_environ_unicode.pop(EnvironUnicode.TEST_VAR)
        self.assertEqual(value, six.text_type("Test four string"))

    def test_environ_in(self):
        os.environ[EnvironUnicode.TEST_VAR] = "Foo"
        self.assertTrue(EnvironUnicode.TEST_VAR in os_environ_unicode)
        self.assertFalse("FakeKey1234" in os_environ_unicode)
