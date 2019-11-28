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
# author: Steven Czerwinski <czerwin@scalyr.com>


__author__ = 'czerwin@scalyr.com'

import os

from scalyr_agent.__scalyr__ import get_install_root, get_package_root, SCALYR_VERSION
from scalyr_agent.test_base import ScalyrTestCase

class TestUtil(ScalyrTestCase):

    def test_version(self):
        self.assertTrue(SCALYR_VERSION.startswith('2.'))

    def test_get_install_root(self):
        self.assertEquals(os.path.basename(get_install_root()), 'scalyr-agent-2')

    def test_get_package_root(self):
        self.assertEquals(os.path.basename(get_package_root()), 'scalyr_agent')