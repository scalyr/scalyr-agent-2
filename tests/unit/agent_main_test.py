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

import os
import shutil
import sys
import subprocess
import platform
import re
from io import open
import functools
import tempfile
import json
import tarfile
import six

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

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
AGENT_MAIN = os.path.abspath(os.path.join(BASE_DIR, "../../scalyr_agent/agent_main.py"))


class AgentMainTestCase(BaseScalyrLogCaptureTestCase):
    def setUp(self):
        super(AgentMainTestCase, self).setUp()
        tmp_fd, self._config_path = tempfile.mkstemp()
        os.close(tmp_fd)

    def tearDown(self):
        os.unlink(self._config_path)

        super(AgentMainTestCase, self).tearDown()

    def _write_mock_config(self, config_data=None):

        if not config_data:
            config_data = {
                "api_key": "bar",
            }

        with open(self._config_path, "wb") as fp:
            fp.write(json.dumps(config_data).encode("utf-8"))

    @staticmethod
    def fake_get_useage_info():
        return 0, 0, 0

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

    def test_no_check_remote_command_line_option(self):
        from scalyr_agent.agent_main import ScalyrAgent

        mock_isatty_true = mock.Mock(return_value=True)

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
        self._write_mock_config()

        # should use default value of False
        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = False

        mock_stdout = mock.Mock()
        mock_stdout.isatty = mock_isatty_true

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

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
        self._write_mock_config()

        # should use overridden value of True
        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = True

        mock_stdout = mock.Mock()
        mock_stdout.isatty = mock_isatty_true

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

    def test_check_remote_if_no_tty(self):
        from scalyr_agent.agent_main import ScalyrAgent

        mock_isatty_true = mock.Mock(return_value=True)
        mock_isatty_false = mock.Mock(return_value=False)

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
        self._write_mock_config()

        # tty is available, should use command line option value when specified
        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = True

        mock_stdout = mock.Mock()
        mock_stdout.isatty = mock_isatty_true

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

        # tty is available, command option is not set, should default to False
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command = "inner_run_with_checks"
        mock_command_options = mock.Mock()
        mock_command_options.no_check_remote = False

        mock_stdout = mock.Mock()
        mock_stdout.isatty = mock_isatty_true

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

        # tty is not available (stdout.isatty returns False), should use check_remote_if_no_tty
        # config option value (config option is set to True)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = False

        mock_stdout = mock.Mock()
        mock_stdout.isatty = mock_isatty_false

        mock_config.check_remote_if_no_tty = True

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(False)

        # tty is not available (stdout.isatty returns False), should use check_remote_if_no_tty
        # config option value (config option is set to False)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = False

        mock_stdout = mock.Mock()
        mock_isatty = mock.Mock()
        mock_stdout.isatty = mock_isatty_false

        mock_config.check_remote_if_no_tty = False

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

        # tty is not available (stdout.isatty is not set), should use check_remote_if_no_tty
        # config option value (config option is set to False)
        agent._ScalyrAgent__perform_config_checks.reset_mock()

        mock_command_options.no_check_remote = False

        mock_stdout = mock.Mock()
        mock_isatty = None
        mock_stdout.isatty = mock_isatty

        mock_config.check_remote_if_no_tty = True

        with mock.patch("scalyr_agent.agent_main.sys.stdout", mock_stdout):
            return_code = agent.main(
                self._config_path, mock_command, mock_command_options
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
                self._config_path, mock_command, mock_command_options
            )
            self.assertEqual(return_code, 7)
            agent._ScalyrAgent__perform_config_checks.assert_called_with(True)

    def test_no_log_messages_printed_on_config_parse_on_status_stop(self):
        log_levels = [
            b"INFO",
            b"DEBUG",
            b"WARN",
            b"ERROR",
        ]

        # Both status and stop command should not produce any log messages on config parse
        for command in ["status", "stop"]:
            process = subprocess.Popen(
                [sys.executable, AGENT_MAIN, command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            stdout, stderr = process.communicate()

            for log_level in log_levels:
                self.assertFalse(
                    log_level in stdout,
                    "Found %s log message in command output which should not be there"
                    % (log_level),
                )
                self.assertFalse(
                    log_level in stderr,
                    "Found %s log message in command output which should not be there"
                    % (log_level),
                )

    def test_essential_monitor_fail(self):
        """
        This test checks that agent raises an error when some of its monitors, which
        are configured as 'stop_agent_if_fails', fail.

        """
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 2. MSI install (only intermediate_certs_path check should be skipped)
        with mock.patch(
            "scalyr_agent.__scalyr__.INSTALL_TYPE", __scalyr__.PACKAGE_INSTALL
        ):

            config_data = {
                "api_key": "0v7dW1EIPpglMcSjGywUdgY9xTNWQP/kas6qHEmiUG5w-",
                "monitors": [
                    {
                        # agent has to fail if this monitor is not alive.
                        "module": "scalyr_agent.builtin_monitors.test_monitor",
                        "gauss_mean": 1,
                        "id": "to_fail",
                        "stop_agent_if_fails": True,
                    },
                    {
                        "module": "scalyr_agent.builtin_monitors.test_monitor",
                        "gauss_mean": 1,
                        "id": "not_to_fail",
                        "stop_agent_if_fails": False,
                    },
                    {
                        "module": "scalyr_agent.builtin_monitors.test_monitor",
                        "id": "not_to_fail_default",
                        "gauss_mean": 1,
                    },
                ],
            }

            self._write_mock_config(config_data=config_data)

            from scalyr_agent.configuration import Configuration

            controller = PlatformController.new_platform()
            config = Configuration(self._config_path, controller.default_paths, None)
            config.parse()

            from scalyr_agent.monitors_manager import MonitorsManager

            monitors_manager = MonitorsManager(
                configuration=config, platform_controller=controller
            )

            monitors_ids = {m.monitor_id: m for m in monitors_manager.monitors}
            monitor_to_fail = monitors_ids["to_fail"]
            monitor_not_to_fail = monitors_ids["not_to_fail"]
            monitor_not_to_fail_default = monitors_ids["not_to_fail_default"]

            assert monitor_to_fail.stop_agent_if_fails is True
            assert monitor_not_to_fail.stop_agent_if_fails is False
            assert monitor_not_to_fail_default.stop_agent_if_fails is False

            assert monitor_to_fail is monitors_manager.find_monitor_by_short_hash(
                short_hash=monitor_to_fail.short_hash
            )
            assert monitor_not_to_fail is monitors_manager.find_monitor_by_short_hash(
                short_hash=monitor_not_to_fail.short_hash
            )
            assert (
                monitor_not_to_fail_default
                is monitors_manager.find_monitor_by_short_hash(
                    short_hash=monitor_not_to_fail_default.short_hash
                )
            )

            agent = ScalyrAgent(PlatformController())
            agent._ScalyrAgent__config = config
            monitor_to_fail.isAlive = mock.Mock()
            monitor_not_to_fail.isAlive = mock.Mock()
            monitor_not_to_fail_default.isAlive = mock.Mock()

            # Attach our real monitor manager to the agent instance.
            with mock.patch.object(
                agent, "_ScalyrAgent__monitors_manager", monitors_manager
            ):

                monitor_to_fail.isAlive.return_value = True
                monitor_not_to_fail.isAlive.return_value = True
                monitor_not_to_fail_default.isAlive.return_value = True

                # Has to succeed with all alive monitors
                agent._fail_if_essential_monitors_are_not_running()

                monitor_not_to_fail.isAlive.return_value = False
                monitor_not_to_fail_default.isAlive.return_value = False

                # Still has to success because monitor which is configured to fail is still alive.
                agent._fail_if_essential_monitors_are_not_running()

                # Now it has to fail.
                monitor_to_fail.isAlive.return_value = False

                with pytest.raises(Exception) as err_info:
                    agent._fail_if_essential_monitors_are_not_running()

                assert (
                    six.text_type(err_info.value)
                    == "Monitor 'test_monitor(to_fail)' with short hash '{}' is not running, "
                    "stopping the agent because it is configured not to run without t"
                    "his monitor.".format(monitor_to_fail.short_hash)
                )


_AGENT_MAIN_PATH = os.path.join(
    __scalyr__.get_install_root(), "scalyr_agent", "agent_main.py"
)


class TestAgentMainArgumentParsing:
    """
    Test various command line inputs to the agent_main.py script.
    """

    def _run_command_get_output(self, cmd):

        final_commands = [sys.executable, _AGENT_MAIN_PATH]
        final_commands.extend(cmd)
        output = subprocess.check_output(
            final_commands,
            stderr=subprocess.PIPE,
        ).decode()

        return output

    def test_help(self):
        output = self._run_command_get_output(
            [
                "-h",
            ]
        )

        assert "{start,stop,status,restart,condrestart,version,config" in output
        assert "-c FILE, --config-file FILE" in output

    def test_empty_command(self):
        with pytest.raises(subprocess.CalledProcessError) as err_info:
            self._run_command_get_output([])

        assert err_info.value.returncode == 2

        # TODO: stderr can not be got from exception in Python 2. Remove that after is it dropped.
        if sys.version_info >= (3,):
            assert (
                "agent_main.py: error: the following arguments are required: command"
                in err_info.value.stderr.decode()
            )

    def test_optional_arg_without_positional(self):
        with pytest.raises(subprocess.CalledProcessError) as err_info:
            self._run_command_get_output(["--config", "path"])

        assert err_info.value.returncode == 2
        # TODO: stderr can not be got from exception in Python 2. Remove that after is it dropped.
        if sys.version_info >= (3,):
            assert (
                "agent_main.py: error: the following arguments are required: command"
                in err_info.value.stderr.decode()
            )

    def test_config(self):
        output = self._run_command_get_output(["config", "-h"])

        # Verify that some config-specific options are there.
        assert "--set-user EXECUTING_USER" in output
        assert "--export-config EXPORT_CONFIG" in output

    @pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Skip windows service test on non-Windows systems.",
    )
    def test_windows_service(self):

        with pytest.raises(subprocess.CalledProcessError) as err_info:
            self._run_command_get_output(["service"])

        # The service return an error, but at least we know that the script processes this case right.
        assert (
            "The service process could not connect to the service controller."
            in err_info.value.stderr.decode()
        )


class TestConfigArgumentParsing:
    def setup(self):
        self.output_dir = tempfile.mkdtemp()
        self.output_file = os.path.join(self.output_dir, "config.tar.gz")

        self.config_path = os.path.join(self.output_dir, "agent.json")
        self.result_dir_path = os.path.join(self.output_dir, "extracted")

        self.extracted_config_path = os.path.join(self.result_dir_path, "agent.json")

    def teardown(self):
        shutil.rmtree(self.output_dir)

    def _write_config(self, config):
        with open(self.config_path, "w") as f:
            f.write(six.ensure_text(json.dumps(config)))

    def _extract_result(self, tar_obj):
        os.mkdir(self.result_dir_path)

        orig_cwd = os.getcwd()
        os.chdir(self.result_dir_path)
        try:
            tar_obj.extractall()
        finally:
            os.chdir(orig_cwd)
            tar_obj.close()

    def test_export_and_import_config(self):
        """
        Test scalyr-agent-3 config --export-config command.
        """

        original_config = {"api_key": "key"}

        self._write_config(config=original_config)

        subprocess.check_call(
            [
                sys.executable,
                _AGENT_MAIN_PATH,
                "config",
                "--export-config",
                self.output_file,
                "--config-file",
                self.config_path,
            ]
        )

        tar = tarfile.open(self.output_file)
        self._extract_result(tar)

        # That same agent config has to be extracted.
        assert os.path.isfile(self.extracted_config_path)

        with open(self.extracted_config_path, "r") as f:
            extracted_config = json.load(f)

        assert extracted_config == original_config

        # Change original config and them import it back.
        changed_config = {"api_key": "key2"}
        self._write_config(config=changed_config)

        subprocess.check_call(
            [
                sys.executable,
                _AGENT_MAIN_PATH,
                "config",
                "--import-config",
                self.output_file,
                "--config-file",
                self.config_path,
            ]
        )

        with open(self.config_path, "r") as f:
            imported_config = json.loads(six.ensure_text(f.read()))

        assert imported_config == original_config

    def test_export_and_import_config_stdout(self):
        """
        Test scalyr-agent-3 config --export-config command, but from stdout.
        """

        original_config = {"api_key": "key"}
        self._write_config(config=original_config)

        output = subprocess.check_output(
            [
                sys.executable,
                _AGENT_MAIN_PATH,
                "config",
                "--export-config",
                "-",
                "--config-file",
                self.config_path,
            ]
        )

        # Write zipped config back to file and
        with open(self.output_file, "wb") as f:
            f.write(output)

        tar = tarfile.open(self.output_file)
        self._extract_result(tar)

        assert os.path.isfile(self.extracted_config_path)

        with open(self.extracted_config_path, "r") as f:
            extracted_config = json.load(f)

        assert extracted_config == original_config

        # Change original config and them import it back.
        changed_config = {"api_key": "key2"}
        self._write_config(config=changed_config)

        with open(self.output_file, "rb") as f:
            subprocess.check_call(
                [
                    sys.executable,
                    _AGENT_MAIN_PATH,
                    "config",
                    "--import-config",
                    "-",
                    "--config-file",
                    self.config_path,
                ],
                stdin=f,
            )

        with open(self.config_path, "r") as f:
            imported_config = json.loads(six.ensure_text(f.read()))

        assert imported_config == original_config
