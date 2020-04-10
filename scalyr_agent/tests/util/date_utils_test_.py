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

from __future__ import absolute_import

import sys
import unittest

import importlib

import six
import mock

if six.PY3:
    reload = importlib.reload


class DateUtilsTestCase(unittest.TestCase):
    def tearDown(self):
        super(DateUtilsTestCase, self).tearDown()

    def test_verify_correct_default_implementation_is_used(self):
        # 1. udatetime is available, we should use that
        sys.modules["udatetime"] = mock.Mock()

        import scalyr_agent.date_parsing_utils

        reload(scalyr_agent.date_parsing_utils)

        self.assertTrue(
            "udatetime"
            in scalyr_agent.date_parsing_utils.rfc3339_to_nanoseconds_since_epoch.__name__
        )
        self.assertTrue(
            "udatetime" in scalyr_agent.date_parsing_utils.rfc3339_to_datetime.__name__
        )

        # 2. udatetime is not available, we should fall back to string split implementation
        del sys.modules["udatetime"]
        import scalyr_agent.date_parsing_utils

        reload(scalyr_agent.date_parsing_utils)

        self.assertTrue(
            "string_split"
            in scalyr_agent.date_parsing_utils.rfc3339_to_nanoseconds_since_epoch.__name__
        )
        self.assertTrue(
            "string_split"
            in scalyr_agent.date_parsing_utils.rfc3339_to_datetime.__name__
        )
