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

from __future__ import unicode_literals
from __future__ import absolute_import

import gc

from scalyr_agent.builtin_monitors.garbage_monitor import GarbageMonitor
from scalyr_agent.test_base import ScalyrTestCase

import mock


class GarbageMonitorTest(ScalyrTestCase):
    @classmethod
    def setUpClass(cls):
        super(GarbageMonitorTest, cls).setUpClass()
        gc.set_debug(gc.DEBUG_SAVEALL)

    @classmethod
    def tearDownClass(cls):
        super(GarbageMonitorTest, cls).tearDownClass()
        gc.set_debug(0)

    def test_gather_sample(self):
        monitor_config = {
            "module": "garbage_monitor",
            "max_object_dump": 10,
            "max_type_dump": 2,
            "monitor_garbage_objects": True,
            "monitor_live_objects": True,
            "monitor_all_unreachable_objects": True,
        }
        mock_logger = mock.Mock()
        monitor = GarbageMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.info.call_args_list

        self.assertTrue("*** Garbage Detector ***" in call_args_list[0][0][0])
        self.assertTrue("garbage objects found" in call_args_list[0][0][0])

        self.assertTrue("*** Garbage Detector ***" in call_args_list[3][0][0])
        self.assertTrue("live objects found" in call_args_list[3][0][0])
