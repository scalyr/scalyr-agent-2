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

import os
import unittest

import mock

from scalyr_agent.__scalyr__ import DEV_INSTALL
from scalyr_agent.build_info import get_build_info
from scalyr_agent.build_info import get_build_revision

__all__ = ["BuildInfoUtilTestCase"]

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
MOCK_BUILD_INFO_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "fixtures/build_info/build_info")
)


class BuildInfoUtilTestCase(unittest.TestCase):
    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_LINUX", MOCK_BUILD_INFO_PATH)
    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_WINDOWS", MOCK_BUILD_INFO_PATH)
    def test_get_build_info_success(self):
        build_info = get_build_info()
        self.assertEqual(build_info["packaged_by"], "jenkins@scalyr.com")
        self.assertEqual(
            build_info["latest_commit"], "7d4c4e2e94242ee25320a75c510d52967cfe50eb"
        )
        self.assertEqual(build_info["from_branch"], "release")
        self.assertEqual(build_info["build_time"], "2020-05-06 17:59:21 UTC")

    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_LINUX", "/tmp/doesnt.exist")
    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_WINDOWS", "/tmp/doesnt.exist")
    def test_get_build_info_build_info_file_doesnt_exist(self):
        build_info = get_build_info()
        self.assertEqual(build_info, {})

    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_LINUX", MOCK_BUILD_INFO_PATH)
    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_WINDOWS", MOCK_BUILD_INFO_PATH)
    @mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", DEV_INSTALL)
    def test_get_build_revision_from_build_info_success(self):
        build_revision = get_build_revision()
        self.assertEqual(build_revision, "7d4c4e2e94242ee25320a75c510d52967cfe50eb")

    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_LINUX", "/tmp/doesnt.exist")
    @mock.patch("scalyr_agent.build_info.BUILD_INFO_PATH_WINDOWS", "/tmp/doesnt.exist")
    @mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", DEV_INSTALL)
    @mock.patch("scalyr_agent.build_info.GIT_GET_HEAD_REVISION_CMD", "echo 'revision'")
    def test_get_build_revision_from_git_success(self):
        build_revision = get_build_revision()
        self.assertEqual(build_revision, "revision")
