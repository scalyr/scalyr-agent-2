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
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import sys

import unittest


if sys.version_info < (2, 5, 0):
    class ScalyrTestCase(unittest.TestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions
        """
        def assertIsNone(self, obj, msg=None):
            """Same as self.assertTrue(obj is None), with a nicer default message."""
            if msg is not None:
                self.assertTrue(obj is None, msg)
            else:
                self.assertTrue(obj is None, '%s is not None' % (str(obj)))

        def assertIsNotNone(self, obj, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(obj is not None, msg)
            else:
                self.assertTrue(obj is not None, '%s is None' % (str(obj)))

        def assertGreater(self, a, b, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(a > b, msg)
            else:
                self.assertTrue(a > b, '%s is greater than %s' % (str(a), str(b)))
else:
    class ScalyrTestCase(unittest.TestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions
        """

        def assertIsNone(self, obj, msg=None):
            unittest.TestCase.assertIsNone(self, obj, msg=msg)

        def assertIsNotNone(self, obj, msg=None):
            unittest.TestCase.assertIsNotNone(self, obj, msg=msg)

        def assertGreater(self, a, b, msg=None):
            unittest.TestCase.assertGreater(self, a, b, msg=msg)