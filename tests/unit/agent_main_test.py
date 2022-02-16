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
from __future__ import unicode_literals

import platform
import re
from io import open
import functools
import tempfile
import json

import mock

from scalyr_agent import __scalyr__
from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase
from scalyr_agent import agent_main, agent_status
from scalyr_agent.scalyr_client import create_client

import pytest

__all__ = ["AgentMainTestCase"]

CORRECT_INIT_PRAGMA = """
### BEGIN INIT INFO
# Provides: scalyr-agent-2
# Required-Start: $network
# Required-Stop: $network
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Description: Manages the Scalyr Agent 2, which provides log copying
#     and back system metric collection.
### END INIT INFO
"""


class AgentMainTestCase(BaseScalyrLogCaptureTestCase):
    @pytest.mark.skipif(
        platform.system() == "Windows", reason="This test is not for Windows."
    )
    @mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.PACKAGE_INSTALL)
    def test_create_client_ca_file_and_intermediate_certs_file_doesnt_exist(self):
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 1. file doesn't exist but cert verification is disabled
        config = mock.Mock()
        config.scalyr_server = "foo.bar.com"
        config.compression_level = 1

        config.verify_server_certificate = False
        config.ca_cert_path = "/tmp/doesnt.exist"
        config.use_new_ingestion = False

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        self.assertTrue(create_client(config))

        # ca_cert_path file doesn't exist
        config.verify_server_certificate = True
        config.ca_cert_path = "/tmp/doesnt.exist"

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        expected_msg = (
            r'Invalid path "/tmp/doesnt.exist" specified for the "ca_cert_path" config '
            "option: file does not exist"
        )

        self.assertRaisesRegexp(
            ValueError, expected_msg, functools.partial(create_client, config)
        )

        # intermediate_certs_path file doesn't exist
        config.verify_server_certificate = True
        config.ca_cert_path = __file__
        config.intermediate_certs_path = "/tmp/doesnt.exist"

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        expected_msg = (
            r'Invalid path "/tmp/doesnt.exist" specified for the '
            '"intermediate_certs_path" config option: file does not exist'
        )

        self.assertRaisesRegexp(
            ValueError, expected_msg, functools.partial(create_client, config)
        )

    def test_ca_cert_files_checks_are_skipped_under_dev(self):
        # Skip those checks under dev and msi install because those final generated certs files
        # are not present under dev install

        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 1. Dev install (boths checks should be skipped)
        with mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.DEV_INSTALL):

            # ca_cert_path file doesn't exist
            config = mock.Mock()
            config.scalyr_server = "foo.bar.com"
            config.compression_level = 1

            config.verify_server_certificate = True
            config.ca_cert_path = "/tmp/doesnt.exist"
            config.use_new_ingestion = False

            agent = ScalyrAgent(PlatformController())
            agent._ScalyrAgent__config = config

            self.assertTrue(create_client(config=config))

            # intermediate_certs_path file doesn't exist
            config.verify_server_certificate = True
            config.ca_cert_path = __file__
            config.intermediate_certs_path = "/tmp/doesnt.exist"

            self.assertTrue(create_client(config=config))

    @pytest.mark.skipif(
        platform.system() != "Windows", reason="This test has to run on Windows."
    )
    def test_ca_cert_files_checks_are_skipped_under_windows(self):

        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 2. MSI install (only intermediate_certs_path check should be skipped)
        with mock.patch(
            "scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.PACKAGE_INSTALL
        ):

            config = mock.Mock()
            config.scalyr_server = "foo.bar.com"
            config.compression_level = 1

            config.verify_server_certificate = True
            config.ca_cert_path = "/tmp/doesnt.exist"
            config.use_new_ingestion = False

            agent = ScalyrAgent(PlatformController())
            agent._ScalyrAgent__config = config

            expected_msg = (
                r'Invalid path "/tmp/doesnt.exist" specified for the "ca_cert_path" config '
                "option: file does not exist"
            )

            self.assertRaisesRegexp(
                ValueError, expected_msg, functools.partial(create_client, config)
            )

            # intermediate_certs_path file doesn't exist
            config.verify_server_certificate = True
            config.ca_cert_path = __file__
            config.intermediate_certs_path = "/tmp/doesnt.exist"

            self.assertTrue(create_client(config=config))

    def test_agent_main_file_contains_correct_init_pragma(self):
        """
        Verify that agent_main.py contains correct init.d comment. It's important that
        "BEGIN INIT INFO" and "END" line contains 3 # (###).

        sys-v is more forgiving and works if there are only two comment marks, but newer versions
        of systemd are not forgiving and don't work with it which means rc.d targets can't be
        created.
        """
        # Make sure we always read the original .py file and not the cached .pyc one
        file_path = agent_main.__file__.replace(".pyc", ".py")

        with open(file_path, "r") as fp:
            content = fp.read()

        msg = (
            "agent_main.py doesn't contain correct init pragma comment. Make sure the comment "
            " is correct and contains thre leading ### on BEGIN and END lines."
        )
        self.assertTrue(CORRECT_INIT_PRAGMA in content, msg)

    def test_skipped_bytes_warnings_one(self):
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        with mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.DEV_INSTALL):

            config = mock.Mock()
            config.scalyr_server = "foo.bar.com"
            config.server_attributes = {"serverHost": "test"}
            config.additional_file_paths = []
            config.compression_level = 1
            config.copying_manager_stats_log_interval = 60
            config.parsed_max_send_rate_enforcement = 12345

            config.verify_server_certificate = True
            config.ca_cert_path = "/tmp/doesnt.exist"

            platform_controller = PlatformController()
            platform_controller.get_usage_info = AgentMainTestCase.fake_get_useage_info
            agent = ScalyrAgent(platform_controller)
            agent._ScalyrAgent__config = config

            client = create_client(config)

            def get_worker_session_statuses_mock(*args, **kwargs):
                return [client]

            with mock.patch.object(agent, "_ScalyrAgent__copying_manager") as m:

                m.generate_status = mock.MagicMock(return_value=None)
                m.get_worker_session_statuses = get_worker_session_statuses_mock
                agent._ScalyrAgent__last_total_bytes_copied = 100
                base_stats = agent_status.OverallStats()
                base_stats.total_bytes_skipped = 500
                base_stats.total_bytes_copied = 900
                test = agent._ScalyrAgent__calculate_overall_stats(
                    base_stats, copy_manager_warnings=True
                )
                self.assertIsNotNone(test)
                print("")
                with open(self.agent_log_path, "r") as f:
                    print((f.read()))
                print("")
                self.assertLogFileContainsLineRegex(
                    ".*"
                    + re.escape(
                        "Warning, skipping copying log lines.  Only copied 0.00001 MB/s log bytes when 0.00002 MB/s were generated over the last 1.0 minutes. This may be due to max_send_rate_enforcement. Log upload has been delayed 0.0 seconds in the last 1.0 minutes  This may be desired (due to excessive bytes from a problematic log file).  Please contact support@scalyr.com for additional help."
                    )
                )

    def test_skipped_bytes_warnings_two(self):
        # NOTE: It's important we split multiple tests into multiple test methods otherwise
        # subsequent checks could be incorrectly asserting on the content generated by the
        # previous test / scenario
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        with mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.DEV_INSTALL):
            config = mock.Mock()
            config.scalyr_server = "foo.bar.com"
            config.server_attributes = {"serverHost": "test"}
            config.additional_file_paths = []
            config.compression_level = 1
            config.copying_manager_stats_log_interval = 60
            config.parsed_max_send_rate_enforcement = None

            config.verify_server_certificate = True
            config.ca_cert_path = "/tmp/doesnt.exist"

            platform_controller = PlatformController()
            platform_controller.get_usage_info = AgentMainTestCase.fake_get_useage_info
            agent = ScalyrAgent(platform_controller)
            agent._ScalyrAgent__config = config

            def get_worker_session_statuses_mock(*args, **kwargs):
                return [client]

            client = create_client(config)

            with mock.patch.object(agent, "_ScalyrAgent__copying_manager") as m:
                m.generate_status = mock.MagicMock(return_value=None)
                m.get_worker_session_statuses = get_worker_session_statuses_mock

                agent._ScalyrAgent__last_total_bytes_copied = 100
                base_stats = agent_status.OverallStats()
                base_stats.total_bytes_skipped = 1000
                base_stats.total_bytes_copied = 900
                test = agent._ScalyrAgent__calculate_overall_stats(
                    base_stats, copy_manager_warnings=True
                )
                self.assertIsNotNone(test)
                print("")
                with open(self.agent_log_path, "r") as f:
                    print((f.read()))
                print("")
                self.assertLogFileContainsLineRegex(
                    ".*"
                    + re.escape(
                        "Warning, skipping copying log lines.  Only copied 0.00001 MB/s log bytes when 0.00003 MB/s were generated over the last 1.0 minutes.  This may be desired (due to excessive bytes from a problematic log file).  Please contact support@scalyr.com for additional help."
                    )
                )

    def test_skipped_bytes_warnings_no_warning_on_0_avg_production_rate(self):
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        with mock.patch("scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.DEV_INSTALL):
            config = mock.Mock()
            config.scalyr_server = "foo.bar.com"
            config.server_attributes = {"serverHost": "test"}
            config.additional_file_paths = []
            config.compression_level = 1
            config.copying_manager_stats_log_interval = 60
            config.parsed_max_send_rate_enforcement = None

            config.verify_server_certificate = True
            config.ca_cert_path = "/tmp/doesnt.exist"

            platform_controller = PlatformController()
            platform_controller.get_usage_info = AgentMainTestCase.fake_get_useage_info
            agent = ScalyrAgent(platform_controller)
            agent._ScalyrAgent__config = config

            def get_worker_session_statuses_mock(*args, **kwargs):
                return [client]

            client = create_client(config)

            with mock.patch.object(agent, "_ScalyrAgent__copying_manager") as m:
                m.generate_status = mock.MagicMock(return_value=None)
                m.get_worker_session_statuses = get_worker_session_statuses_mock

                base_stats = agent_status.OverallStats()
                base_stats.total_bytes_skipped = 1000
                base_stats.total_bytes_produced = 0
                base_stats.last_total_bytes_produced = 0
                base_stats.__last_total_bytes_copied = 0
                test = agent._ScalyrAgent__calculate_overall_stats(
                    base_stats, copy_manager_warnings=True
                )
                self.assertIsNotNone(test)
                print("")
                with open(self.agent_log_path, "r") as f:
                    print((f.read()))
                print("")
                self.assertLogFileDoesntContainsLineRegex(
                    ".*" + re.escape("Warning, skipping copying log lines.")
                )

    def test_check_remote_if_no_tty(self):
        from scalyr_agent.agent_main import ScalyrAgent

        mock_config = mock.Mock()

        platform_controller = mock.Mock()
        platform_controller.default_paths = mock.Mock()

        agent = ScalyrAgent(platform_controller)
        agent._ScalyrAgent__config = mock_config
        agent._ScalyrAgent__read_and_verify_config = mock.Mock()
        agent._ScalyrAgent__perform_config_checks = mock.Mock()
        agent._ScalyrAgent__run = mock.Mock()

        agent._ScalyrAgent__read_and_verify_config.return_value = mock_config

        agent._ScalyrAgent__run.return_value = 7
        mock_config_path = self._write_mock_config()

        # tty is available, should use command line option value when specified
        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = True

        return_code = agent.main(mock_config_path, mock_command, mock_command_options)
        self.assertEqual(return_code, 7)
        agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

        # tty is available, command option is not set, should default to False
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = None

        return_code = agent.main(mock_config_path, mock_command, mock_command_options)
        self.assertEqual(return_code, 7)
        agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

        # tty is not available (stdout.isatty returns False), should use check_remote_if_no_tty
        # config option value (config option is set to True)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = None

        mock_stdout = mock.Mock()
        mock_isatty = mock.Mock()
        mock_isatty.return_value = False
        mock_stdout.isatty = mock_isatty

        mock_config.check_remote_if_no_tty = True

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                mock_config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

        # tty is not available (stdout.isatty returns False), should use check_remote_if_no_tty
        # config option value (config option is set to False)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = None

        mock_stdout = mock.Mock()
        mock_isatty = mock.Mock()
        mock_isatty.return_value = False
        mock_stdout.isatty = mock_isatty

        mock_config.check_remote_if_no_tty = False

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                mock_config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

        # tty is not available (stdout.isatty is not set), should use check_remote_if_no_tty
        # config option value (config option is set to False)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = None

        mock_stdout = mock.Mock()
        mock_isatty = None
        mock_stdout.isatty = mock_isatty

        mock_config.check_remote_if_no_tty = True

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                mock_config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

        # tty is not available (stdout.isatty is not set), should use check_remote_if_no_tty
        # config option value (config option is set to True)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = None

        mock_stdout = mock.Mock()
        mock_isatty = None
        mock_stdout.isatty = mock_isatty

        mock_config.check_remote_if_no_tty = False

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                mock_config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

    def _write_mock_config(self):
        _, tmp_path = tempfile.mkstemp()

        config_data = {
            "api_key": "bar",
        }

        with open(tmp_path, "wb") as fp:
            fp.write(json.dumps(config_data).encode("utf-8"))

        return tmp_path

    @staticmethod
    def fake_get_useage_info():
        return 0, 0, 0
