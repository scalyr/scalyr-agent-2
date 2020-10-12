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

from __future__ import print_function
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Add directory which contains smoketests package to PYTHONPATH
PACKAGE_DIR = os.path.abspath(
    os.path.join(BASE_DIR, "../../.circleci/docker_unified_smoke_unit")
)
sys.path.append(PACKAGE_DIR)

from smoketest.smoketest import StandaloneSmokeTestActor  # pylint: disable=import-error


class StandaloneSmokeTestActorTestCase(unittest.TestCase):
    def test_make_query_url(self):
        # Verify special characters are correctly url encoded
        st = StandaloneSmokeTestActor(
            max_wait=0,
            scalyr_server="https://www.scalyr.com",
            monitored_logfile="test.txt",
        )

        filter_dict = {"a": 1, "bar": False, "baz": True, "str": "value"}
        server_host = "foo.bar.com"
        message = "test message 1"

        expected_url = (
            "https://www.scalyr.com/api/query?queryType=log&maxCount=1&startTime=10m"
            "&token=None&filter=$logfile==%22test.txt%22+and+"
            "$serverHost==%22foo.bar.com%22+and+a==1+and+bar==%22false%22"
            "+and+baz==%22true%22"
            "+and+str==%22value%22+and+$message+contains+%22test+message+1%22"
        )

        url = st._make_query_url(
            filter_dict=filter_dict, message=message, override_serverHost=server_host
        )
        print(expected_url)
        print(url)
        self.assertEqual(url, expected_url)
