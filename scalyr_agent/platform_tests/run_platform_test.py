# Copyright 2015 Scalyr Inc.
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
# author: Saurabh Jain <saurabh@scalyr.com>

__author__ = 'saurabh@scalyr.com'

import unittest
from subprocess import call
import os


class cd:
    """Context manager for changing the current working directory
    From: https://stackoverflow.com/questions/431684/how-do-i-cd-in-python
    """
    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class RunPlatformTests(unittest.TestCase):
    """
    Runs Scalyr Agent Tests on all platforms
    """
    @unittest.skipUnless(os.environ.get("SCALYR_NO_SKIP_TESTS"), "Platform Tests")
    def test_alpine(self):
        with cd("scalyr_agent/platform_tests/alpine"):
            call(["pwd"])
            call(["docker", "build", "-t",  "scalyr:python_2-alpine", "."])
            call(["docker", "run", "scalyr:python_2-alpine", "python", "run_tests.py", "--verbose"])
