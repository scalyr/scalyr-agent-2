# Copyright 2021 Scalyr Inc.
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

import platform

import mock
import pytest

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

if platform.system() == "Windows":
    WINDOWS = True
else:
    WINDOWS = False


@pytest.mark.windows_platform
class WindowsPlatformControllerTestCase(ScalyrTestCase):
    @skipIf(not WINDOWS or False, "Skipping tests under non-Windows platform")
    @mock.patch("scalyr_agent.platform_windows._set_config_path_registry_entry")
    def test_start_agent_service_friendly_error_on_insufficient_permissions(
        self, mock_set_config_path_registry_entry
    ):
        from scalyr_agent.platform_windows import WindowsPlatformController

        mock_set_config_path_registry_entry.side_effect = Exception("Access is denied")

        def noop():
            pass

        controller = WindowsPlatformController()
        expected_msg = r".*Unable to set registry entry.*"
        self.assertRaisesRegexp(
            Exception, expected_msg, controller.start_agent_service, noop, None
        )

    @skipIf(not WINDOWS or False, "Skipping tests under non-Windows platform")
    @mock.patch("win32serviceutil.StopService")
    def test_stop_agent_service_friendly_error_on_insufficient_permissions(
        self, mock_StopService
    ):
        from scalyr_agent.platform_windows import WindowsPlatformController

        mock_StopService.side_effect = Exception("Access is denied")
        controller = WindowsPlatformController()
        expected_msg = r".*Unable to stop agent process.*"
        self.assertRaisesRegexp(
            Exception, expected_msg, controller.stop_agent_service, False
        )
