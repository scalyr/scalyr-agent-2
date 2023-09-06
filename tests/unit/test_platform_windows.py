# Copyright 2021-2023 Scalyr Inc.
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

import argparse
import platform

import mock
import pytest

if platform.system() == "Windows":
    from scalyr_agent.platform_windows import WindowsPlatformController

from scalyr_agent.platform_controller import CannotExecuteAsUser
from scalyr_agent.test_base import ScalyrTestCase, skipIf


@pytest.mark.windows_platform
class WindowsPlatformControllerTestCase(ScalyrTestCase):
    @skipIf(platform.system() != "Windows", "Skipping tests under non-Windows platform")
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

    @skipIf(platform.system() != "Windows", "Skipping tests under non-Windows platform")
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

    @skipIf(platform.system() != "Windows", "Skipping tests under non-Windows platform")
    def test_run_as_user_as_any_administrator(self):
        with mock.patch("win32api.GetComputerName", return_value="Domain"), mock.patch(
            "scalyr_agent.platform_windows.WindowsPlatformController._all_admin_names",
            return_value=["Domain\\Admin1", "Domain\\Admin2"],
        ), mock.patch(
            "scalyr_agent.platform_windows.WindowsPlatformController._run_as_administrators"
        ):

            platform_controller = WindowsPlatformController()
            parser = argparse.ArgumentParser()
            platform_controller.add_options(parser)
            platform_controller.consume_options(
                parser.parse_args(["--no-warn-escalation"])
            )

            run_as_user_args = ["script", "python", []]
            platform_controller.run_as_user("Domain\\Administrators", *run_as_user_args)
            self.assertEqual(platform_controller._run_as_administrators.call_count, 1)

            platform_controller.run_as_user("Domain\\Admin1", *run_as_user_args)
            self.assertEqual(platform_controller._run_as_administrators.call_count, 2)

            platform_controller.run_as_user("Domain\\Admin2", *run_as_user_args)
            self.assertEqual(platform_controller._run_as_administrators.call_count, 3)

            with self.assertRaisesRegexp(
                CannotExecuteAsUser, "as an Administrator account"
            ):
                platform_controller.run_as_user("Domain\\User", *run_as_user_args)
