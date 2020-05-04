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

from __future__ import absolute_import

__author__ = "saurabh@scalyr.com"

"""
This module is used to run the tests under tests/unit on different OS platforms
with different Python versions.

We do this by:
1) iterating over all the Dockerfiles under scalyr_agent/platform_tests
2) for each Dockerfile:
    i)   create a Docker Image
    ii)  run a container
    iii) run the tests.
3) Once the tests have run, destroy the container and the images created.

"""

import unittest
from subprocess import call
import os

from scalyr_agent.test_base import skipUnless
from scalyr_agent import compat


class WorkingDirectory:
    """Context manager for changing the current working directory
    From: https://stackoverflow.com/questions/431684/how-do-i-cd-in-python
    """

    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype=None, value=None, traceback=None):
        os.chdir(self.savedPath)


class RunPlatformTests(unittest.TestCase):
    """
    Runs Scalyr Agent Tests on all platforms
    """

    @skipUnless(compat.os_environ_unicode.get("SCALYR_NO_SKIP_TESTS"), "Platform Tests")
    def test_alpine(self):
        wd = WorkingDirectory("scalyr_agent/platform_tests/alpine")
        try:
            wd.__enter__()
            call(["docker", "build", "-t", "scalyr:python_2-alpine", "."])
            call(
                [
                    "docker",
                    "run",
                    "--name",
                    "scalyr_container_alpine",
                    "scalyr:python_2-alpine",
                    "python",
                    "run_tests.py",
                    "--verbose",
                ]
            )
        finally:
            wd.__exit__()

    @skipUnless(compat.os_environ_unicode.get("SCALYR_NO_SKIP_TESTS"), "Platform Tests")
    def test_wheezy(self):
        wd = WorkingDirectory("scalyr_agent/platform_tests/wheezy")
        try:
            wd.__enter__()
            call(["docker", "build", "-t", "scalyr:python_2-wheezy", "."])
            call(
                [
                    "docker",
                    "run",
                    "--name",
                    "scalyr_container_wheezy",
                    "scalyr:python_2-wheezy",
                    "python",
                    "run_tests.py",
                    "--verbose",
                ]
            )
        finally:
            wd.__exit__()

    @skipUnless(compat.os_environ_unicode.get("SCALYR_NO_SKIP_TESTS"), "Platform Tests")
    def test_jessie(self):
        wd = WorkingDirectory("scalyr_agent/platform_tests/jessie")
        try:
            wd.__enter__()
            call(["docker", "build", "-t", "scalyr:python_2-jessie", "."])
            call(
                [
                    "docker",
                    "run",
                    "--name",
                    "scalyr_container_jessie",
                    "scalyr:python_2-jessie",
                    "python",
                    "run_tests.py",
                    "--verbose",
                ]
            )
        finally:
            wd.__exit__()

    @classmethod
    @skipUnless(compat.os_environ_unicode.get("SCALYR_NO_SKIP_TESTS"), "Platform Tests")
    def tearDownClass(cls):
        call(
            [
                "docker",
                "stop",
                "scalyr_container_alpine",
                "scalyr_container_wheezy",
                "scalyr_container_jessie",
            ]
        )
        call(
            [
                "docker",
                "rm",
                "scalyr_container_alpine",
                "scalyr_container_wheezy",
                "scalyr_container_jessie",
            ]
        )
        call(
            [
                "docker",
                "rmi",
                "scalyr:python_2-alpine",
                "scalyr:python_2-wheezy",
                "scalyr:python_2-jessie",
            ]
        )
