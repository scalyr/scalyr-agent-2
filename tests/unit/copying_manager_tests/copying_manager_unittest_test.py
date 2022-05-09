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
#
# Here are the test cases that are written for unittest library.

from __future__ import absolute_import
from __future__ import unicode_literals

import os
import shutil
import tempfile
from io import open
import platform
import sys

if False:
    from typing import List


import pytest

from scalyr_agent import util as scalyr_util
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.copying_manager.worker import CopyingParameters
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils
from tests.unit.copying_manager_tests.common import TestableCopyingManager
from scalyr_agent.configuration import Configuration

from tests.unit.copying_manager_tests.copying_manager_test import (
    FakeMonitor1,
    FakeMonitor,
)
from tests.unit.copying_manager_tests.test_environment import TestingConfiguration
from six.moves import range

ONE_MIB = 1024 * 1024
ALMOST_SIX_MB = 5900000


def pytest_addoption(parser):
    parser.addoption("--all", action="store_true", help="run all combinations")


def pytest_generate_tests(metafunc):
    if "worker_type" in metafunc.fixturenames:
        test_params = ["thread"]
        # if the OS is not Windows / OSX and python version > 2.7 then also do the multiprocess workers testing.
        if platform.system() not in ["Windows", "Darwin"] and sys.version_info >= (
            2,
            7,
        ):
            test_params.append("process")

        metafunc.parametrize("worker_type", test_params)


def _create_test_copying_manager(configuration, monitors, auto_start=True):
    # type: (Configuration, List, bool) -> TestableCopyingManager
    """
    :param configuration:
    :param monitors:
    :param auto_start:
        If True, do a proper initialization where the copying manager has scanned the current log file and is ready
    for the next loop, we let it go all the way through the loop once and wait in the sleeping state.
        If False, manual start of copying manager is needed. This is useful if we need to pause copying manager
    before sleeping state, or specify "logs_initial_positions".
    :return:
    """
    manager = TestableCopyingManager(configuration, monitors)
    # To do a proper initialization where the copying manager has scanned the current log file and is ready
    # for the next loop, we let it go all the way through the loop once and wait in the sleeping state.
    # But in some cases we have to stop it earlier, so we can specify "stop_at" parameter.
    if auto_start:
        manager.start_manager()
        manager.run_and_stop_at(TestableCopyingManager.SLEEPING)

    return manager


class BaseTest(object):
    def assertEquals(self, expexted, actual):
        assert expexted == actual


class TestDynamicLogPathTest(BaseTest):
    @pytest.fixture(autouse=True)
    def setup(self, worker_type):
        self.use_multiprocessing_workers = worker_type == "process"
        self._temp_dir = tempfile.mkdtemp()
        self._data_dir = os.path.join(self._temp_dir, "data")
        self._log_dir = os.path.join(self._temp_dir, "log")
        self._config_dir = os.path.join(self._temp_dir, "config")
        self._config_file = os.path.join(self._config_dir, "agentConfig.json")
        self._config_fragments_dir = os.path.join(self._config_dir, "configs.d")

        os.makedirs(self._config_fragments_dir)
        os.makedirs(self._data_dir)
        os.makedirs(self._log_dir)

    def teardown(self):
        if self._manager is not None:
            self._manager.stop_manager()
        shutil.rmtree(self._config_dir)

    def fake_scan(self, response="success"):
        if self._manager is not None:
            self._manager.perform_scan()
            _, responder_callback = self._manager.wait_for_rpc()
            responder_callback(response)

    def create_copying_manager(self, config, monitor_agent_log=False):

        if "api_key" not in config:
            config["api_key"] = "fake"

        if not monitor_agent_log:
            config["implicit_agent_log_collection"] = False

        config["use_multiprocessing_workers"] = self.use_multiprocessing_workers

        f = open(self._config_file, "w")
        if f:

            f.write(scalyr_util.json_encode(config))
            f.close()

        default_paths = DefaultPaths(self._log_dir, self._config_file, self._data_dir)

        configuration = TestingConfiguration(self._config_file, default_paths, None)
        configuration.parse()
        self._manager = _create_test_copying_manager(configuration, [])

    def test_add_path(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

    def test_add_duplicate_path_same_monitor(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()

        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

    def test_add_duplicate_path_different_monitor(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        self._manager.add_log_config("unittest2", log_config)
        self.fake_scan()

        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

    def test_update_config(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()

        log_config["parser"] = "newParser"
        self._manager.update_log_config("unittest", log_config)
        self.fake_scan()

        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)
        self.assertEquals("newParser", matchers[0].config["parser"])

    def test_update_config_different_monitor(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()

        log_config["parser"] = "newParser"
        self._manager.update_log_config("unittest2", log_config)
        self.fake_scan()

        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)
        self.assertEquals("agent-metrics", matchers[0].config["parser"])

    def test_update_config_not_monitored(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.update_log_config("unittest", log_config)
        self.fake_scan()

        matchers = self._manager.log_matchers
        self.assertEquals(0, len(matchers))

    def test_schedule_log_path_for_removal_and_re_add_before_actual_removal(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

        assert path not in self._get_manager_log_pending_removal()

        self._manager.schedule_log_path_for_removal("unittest", path)
        assert path in self._get_manager_log_pending_removal()

        # We use force_add=True when adding the log file which means scheduled removal should be
        # canceled / removed
        self._manager.add_log_config("unittest", log_config, force_add=True)
        assert path not in self._get_manager_log_pending_removal()

        self.fake_scan()
        self.fake_scan()

        assert path not in self._get_manager_log_pending_removal()

        # Matcher should still be there since removal should have been canceled
        matchers = self._manager.log_matchers
        assert len(matchers) == 1

    def test_schedule_log_path_for_removal(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

        self._manager.schedule_log_path_for_removal("unittest", path)
        self.fake_scan()
        self.fake_scan()
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(0, len(matchers))

    def test_schedule_pending_log_path_for_removal(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1")

        log_config = {"path": path}

        # Add new log and remove it right after addition.
        # Expected that it will remain until all bytes have been read.
        self._manager.add_log_config("unittest", log_config)
        self._manager.schedule_log_path_for_removal("unittest", path)

        # The first scan only adds file matcher and file processor, the read, will be on next iteration.
        # Also it sets matcher as pending removal, but keeps it until file has been read.
        self.fake_scan()
        # File processor performs read on previously added file processor.
        # It should reach OEF, but it won't be removed yet, because it has new bytes.
        self.fake_scan()
        # Processor performs another read, but there aren't new bytes.
        # File processor and file matcher can be removed.
        self.fake_scan()

        matchers = self._manager.log_matchers

        self.assertEquals(0, len(matchers))

    def test_schedule_log_path_for_removal_different_monitor(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

        self._manager.schedule_log_path_for_removal("unittest2", path)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))

    def test_remove_log_path(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        path2 = os.path.join(self._log_dir, "newlog2.log")
        self.append_log_lines(path2, "line1\n")

        log_config2 = {"path": path2}

        self._manager.add_log_config("unittest", log_config)
        self._manager.add_log_config("unittest", log_config2)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(2, len(matchers))
        self.assertEquals(path, matchers[0].log_path)
        self.assertEquals(path2, matchers[1].log_path)

        self._manager.remove_log_path("unittest", path)
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))

        self._manager.remove_log_path("unittest", path2)
        matchers = self._manager.log_matchers
        self.assertEquals(0, len(matchers))

    def test_add_after_remove(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

        self._manager.remove_log_path("unittest", path)
        self.fake_scan()
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(0, len(matchers))
        self.assertEquals(0, self._manager.dynamic_matchers_count())

        self._manager.add_log_config("otherunittest", log_config)
        self.fake_scan()
        self.assertEquals(1, self._manager.dynamic_matchers_count())
        self.assertEquals(path, matchers[0].log_path)

    def test_remove_log_path_different_monitor(self):
        config = {}
        self.create_copying_manager(config)
        self.fake_scan()

        path = os.path.join(self._log_dir, "newlog.log")
        self.append_log_lines(path, "line1\n")

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)
        self.fake_scan()
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))
        self.assertEquals(path, matchers[0].log_path)

        self._manager.remove_log_path("unittest2", path)
        matchers = self._manager.log_matchers
        self.assertEquals(1, len(matchers))

    def test_remove_glob_path(self):

        glob_root = os.path.join(self._temp_dir, "containers")
        os.makedirs(glob_root)
        config = {"logs": [{"path": "%s/*/*" % glob_root}]}

        path = os.path.join(glob_root, "container", "container.log")
        os.makedirs(os.path.dirname(path))

        f = open(path, "w")
        if f:
            f.close()

        self.create_copying_manager(config)

        # At this point, the test state = SLEEPING (after init)
        # perform_scan() calls run_and_stop_at(SENDING, required=SLEEPING)
        # Since the test state is already SLEEPING, the required transition is 'consumed' and the require-transition
        # assertion passes and the next-round required transition becomes NONE
        self.fake_scan()

        log_config = {"path": path}

        self._manager.add_log_config("unittest", log_config)

        self.fake_scan()

        self._manager.schedule_log_path_for_removal("unittest", log_config["path"])

        self.assertEquals(1, self._manager.logs_pending_removal_count())

        self.fake_scan()

        self.assertEquals(0, self._manager.logs_pending_removal_count())

    def append_log_lines(self, filename, *args):
        fp = open(filename, "a")
        for line in args:
            fp.write(line)
            fp.write("\n")
        fp.close()

    def _get_manager_log_pending_removal(self):
        # pylint: disable=no-member
        return self._manager._CopyingManager__logs_pending_removal
        # pylint: enable=no-member


class CopyingParamsLegacyTest(ScalyrTestCase):
    def setUp(self):
        super(CopyingParamsLegacyTest, self).setUp()
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, "agentConfig.json")
        self.__config_fragments_dir = os.path.join(self.__config_dir, "configs.d")
        os.makedirs(self.__config_fragments_dir)

        fp = open(self.__config_file, "w")
        fp.write('{api_key: "fake", max_send_rate_enforcement: "legacy"}')
        fp.close()

        config = self.__create_test_configuration_instance()
        config.parse()
        self.test_params = CopyingParameters(config)

    def test_initial_settings(self):
        self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MIB)
        self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_no_events_being_sent(self):
        for i in range(0, 5):
            self.test_params.update_params("success", 0)
            self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MIB)
            self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_small_events_being_sent(self):
        self.test_params.current_sleep_interval = 1
        self._run(
            "success",
            10 * 1024,
            [1.5, ONE_MIB],
            [2.25, ONE_MIB],
            [3.375, ONE_MIB],
            [5, ONE_MIB],
        )

    def test_too_many_events_being_sent(self):
        self.test_params.current_sleep_interval = 5

        self._run(
            "success",
            200 * 1024,
            [3.0, ONE_MIB],
            [1.8, ONE_MIB],
            [1.08, ONE_MIB],
            [1, ONE_MIB],
        )

    def test_request_too_big(self):
        self.test_params.current_sleep_interval = 1

        self.test_params.update_params("requestTooLarge", 300 * 1024)
        self.assertAlmostEquals(
            self.test_params.current_bytes_allowed_to_send, 150 * 1024
        )

        self.test_params.update_params("requestTooLarge", 150 * 1024)
        self.assertAlmostEquals(
            self.test_params.current_bytes_allowed_to_send, 100 * 1024
        )

    def test_error_back_off(self):
        self.test_params.current_sleep_interval = 3
        self._run(
            "error",
            200 * 1024,
            [4.5, ONE_MIB],
            [6.75, ONE_MIB],
            [10.125, ONE_MIB],
            [15.1875, ONE_MIB],
            [22.78125, ONE_MIB],
            [30, ONE_MIB],
        )

    def _run(self, status, bytes_sent, *expected_sleep_interval_allowed_bytes):
        """Verifies that when test_params is updated with the specified status and bytes sent the current sleep
        interval and allowed bytes is updated to the given values.

        This will call test_params.update_params N times where N is the number of additional arguments supplied.
        After the ith invocation of test_params.update_params, the values for the current_sleep_interval and
        current_bytes_allowed_to_send will be checked against the ith additional parameter.

        @param status: The status to use when invoking test_params.update_params.
        @param bytes_sent: The number of bytes sent to use when invoking test_params.update_params.
        @param expected_sleep_interval_allowed_bytes: A variable number of two element arrays where the first element
            is the expected value for current_sleep_interval and the second is the expected value of
            current_bytes_allowed_to_send. Each subsequent array represents what those values should be after invoking
            test_params.update_param again.
        """
        for expected_result in expected_sleep_interval_allowed_bytes:
            self.test_params.update_params(status, bytes_sent)
            self.assertAlmostEquals(
                self.test_params.current_sleep_interval, expected_result[0]
            )
            self.assertAlmostEquals(
                self.test_params.current_bytes_allowed_to_send, expected_result[1]
            )

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config["path"]

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config["module"]
            self.config = config
            self.log_config = {"path": self.module_name.split(".")[-1] + ".log"}

    def __create_test_configuration_instance(self):

        default_paths = DefaultPaths(
            "/var/log/scalyr-agent-2",
            "/etc/scalyr-agent-2/agent.json",
            "/var/lib/scalyr-agent-2",
        )
        return TestingConfiguration(self.__config_file, default_paths, None)


class CopyingParamsTest(ScalyrTestCase):
    def setUp(self):
        super(CopyingParamsTest, self).setUp()
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, "agentConfig.json")
        self.__config_fragments_dir = os.path.join(self.__config_dir, "configs.d")
        os.makedirs(self.__config_fragments_dir)

        fp = open(self.__config_file, "w")
        fp.write('{api_key: "fake"}')
        fp.close()

        config = self.__create_test_configuration_instance()
        config.parse()
        self.test_params = CopyingParameters(config)

    def test_initial_settings(self):
        self.assertEquals(self.test_params.current_bytes_allowed_to_send, ALMOST_SIX_MB)
        self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_no_events_being_sent(self):
        for i in range(0, 5):
            self.test_params.update_params("success", 0)
            self.assertEquals(
                self.test_params.current_bytes_allowed_to_send, ALMOST_SIX_MB
            )
            self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_small_events_being_sent(self):
        self.test_params.current_sleep_interval = 0.1
        self._run(
            "success",
            10 * 1024,
            [0.15, ALMOST_SIX_MB],
            [0.225, ALMOST_SIX_MB],
            [0.3375, ALMOST_SIX_MB],
            [0.50625, ALMOST_SIX_MB],
        )

    def test_too_many_events_being_sent(self):
        self.test_params.current_sleep_interval = 1

        self._run(
            "success",
            200 * 1024,
            [0.6, ALMOST_SIX_MB],
            [0.36, ALMOST_SIX_MB],
            [0.216, ALMOST_SIX_MB],
            [0.1296, ALMOST_SIX_MB],
        )

    def test_request_too_big(self):
        self.test_params.current_sleep_interval = 1

        self.test_params.update_params("requestTooLarge", 300 * 1024)
        self.assertAlmostEquals(
            self.test_params.current_bytes_allowed_to_send, 150 * 1024
        )

        self.test_params.update_params("requestTooLarge", 150 * 1024)
        self.assertAlmostEquals(
            self.test_params.current_bytes_allowed_to_send, 100 * 1024
        )

    def test_error_back_off(self):
        self.test_params.current_sleep_interval = 3
        self._run(
            "error",
            200 * 1024,
            [4.5, ALMOST_SIX_MB],
            [6.75, ALMOST_SIX_MB],
            [10.125, ALMOST_SIX_MB],
            [15.1875, ALMOST_SIX_MB],
            [22.78125, ALMOST_SIX_MB],
            [30, ALMOST_SIX_MB],
        )

    def _run(self, status, bytes_sent, *expected_sleep_interval_allowed_bytes):
        """Verifies that when test_params is updated with the specified status and bytes sent the current sleep
        interval and allowed bytes is updated to the given values.

        This will call test_params.update_params N times where N is the number of additional arguments supplied.
        After the ith invocation of test_params.update_params, the values for the current_sleep_interval and
        current_bytes_allowed_to_send will be checked against the ith additional parameter.

        @param status: The status to use when invoking test_params.update_params.
        @param bytes_sent: The number of bytes sent to use when invoking test_params.update_params.
        @param expected_sleep_interval_allowed_bytes: A variable number of two element arrays where the first element
            is the expected value for current_sleep_interval and the second is the expected value of
            current_bytes_allowed_to_send. Each subsequent array represents what those values should be after invoking
            test_params.update_param again.
        """
        for expected_result in expected_sleep_interval_allowed_bytes:
            self.test_params.update_params(status, bytes_sent)
            self.assertAlmostEquals(
                self.test_params.current_sleep_interval, expected_result[0]
            )
            self.assertAlmostEquals(
                self.test_params.current_bytes_allowed_to_send, expected_result[1]
            )

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config["path"]

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config["module"]
            self.config = config
            self.log_config = {"path": self.module_name.split(".")[-1] + ".log"}

    def __create_test_configuration_instance(self):

        default_paths = DefaultPaths(
            "/var/log/scalyr-agent-2",
            "/etc/scalyr-agent-2/agent.json",
            "/var/lib/scalyr-agent-2",
        )
        return TestingConfiguration(self.__config_file, default_paths, None)


class CopyingManagerInitializationTest(ScalyrTestCase):
    def test_from_config_file(self):
        test_manager = self._create_test_instance([{"path": "/tmp/hi.log"}], [])
        self.assertEquals(len(test_manager.log_matchers), 3)
        self.assertEquals(test_manager.log_matchers[0].config["path"], "/tmp/hi.log")
        self.assertEquals(
            test_manager.log_matchers[1].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent.log",
        ),

        # test if there are implicit log configs for the worker session agent logs.
        self.assertEquals(
            test_manager.log_matchers[2].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent-worker-session-*.log",
        )

    def test_from_monitors(self):
        test_manager = self._create_test_instance([], [{"path": "/tmp/hi_monitor.log"}])
        self.assertEquals(len(test_manager.log_matchers), 3)
        self.assertEquals(
            test_manager.log_matchers[0].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent.log",
        )
        # test if there are implicit log configs for the worker session agent logs.
        self.assertEquals(
            test_manager.log_matchers[1].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent-worker-session-*.log",
        )
        self.assertEquals(
            test_manager.log_matchers[2].config["path"], "/tmp/hi_monitor.log"
        )
        self.assertEquals(
            test_manager.log_matchers[2].config["attributes"]["parser"], "agent-metrics"
        )

    def test_multiple_monitors_for_same_file(self):
        test_manager = self._create_test_instance(
            [],
            [
                {"path": "/tmp/hi_monitor.log"},
                {"path": "/tmp/hi_monitor.log"},
                {"path": "/tmp/hi_second_monitor.log"},
            ],
        )
        self.assertEquals(len(test_manager.log_matchers), 4)
        self.assertEquals(
            test_manager.log_matchers[0].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent.log",
        )
        # test if there are implicit log configs for the worker session agent logs.
        self.assertEquals(
            test_manager.log_matchers[1].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent-worker-session-*.log",
        )
        self.assertEquals(
            test_manager.log_matchers[2].config["path"], "/tmp/hi_monitor.log"
        )
        self.assertEquals(
            test_manager.log_matchers[2].config["attributes"]["parser"], "agent-metrics"
        )
        self.assertEquals(
            test_manager.log_matchers[3].config["path"], "/tmp/hi_second_monitor.log"
        )
        self.assertEquals(
            test_manager.log_matchers[3].config["attributes"]["parser"], "agent-metrics"
        )

    def test_monitor_log_config_updated(self):
        test_manager = self._create_test_instance([], [{"path": "hi_monitor.log"}])
        self.assertEquals(len(test_manager.log_matchers), 3)
        self.assertEquals(
            test_manager.log_matchers[0].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent.log",
        )
        # test if there are implicit log configs for the worker session agent logs.
        self.assertEquals(
            test_manager.log_matchers[1].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "agent-worker-session-*.log",
        )
        self.assertEquals(
            test_manager.log_matchers[2].config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "hi_monitor.log",
        )

        # We also verify the monitor instance itself's log config object was updated to have the full path.
        self.assertEquals(
            self.__monitor_fake_instances[0].log_config["path"],
            "/var/log/scalyr-agent-2" + os.sep + "hi_monitor.log",
        )

    def test_remove_log_path_with_non_existing_path(self):
        test_manager = self._create_test_instance([], [{"path": "test.log"}])
        # check that removing a non-existent path runs without throwing an exception
        test_manager.remove_log_path("test_monitor", "blahblah.log")

    def test_get_server_attribute(self):
        logs_json_array = []
        config = ScalyrTestUtils.create_configuration(
            extra_toplevel_config={"logs": logs_json_array}
        )
        self.__monitor_fake_instances = []
        monitor_a = FakeMonitor1({"path": "testA.log"}, id="a", attribute_key="KEY_a")
        monitor_b = FakeMonitor1({"path": "testB.log"}, id="b", attribute_key="KEY_b")
        self.__monitor_fake_instances.append(monitor_a)
        self.__monitor_fake_instances.append(monitor_b)
        copy_manager = CopyingManager(config, self.__monitor_fake_instances)
        attribs = copy_manager.expanded_server_attributes
        self.assertEquals(attribs["KEY_a"], monitor_a.attribute_value)
        self.assertEquals(attribs["KEY_b"], monitor_b.attribute_value)

    def test_get_server_attribute_no_override(self):
        logs_json_array = []
        config = ScalyrTestUtils.create_configuration(
            extra_toplevel_config={"logs": logs_json_array}
        )
        self.__monitor_fake_instances = []
        monitor_a = FakeMonitor1(
            {"path": "testA.log"}, id="a", attribute_key="common_key"
        )
        monitor_b = FakeMonitor1(
            {"path": "testB.log"}, id="b", attribute_key="common_key"
        )
        self.__monitor_fake_instances.append(monitor_a)
        self.__monitor_fake_instances.append(monitor_b)
        copy_manager = CopyingManager(config, self.__monitor_fake_instances)
        if monitor_a.access_order < monitor_b.access_order:
            first_accessed = monitor_a
            second_accessed = monitor_b
        else:
            first_accessed = monitor_b
            second_accessed = monitor_a
        self.assertLess(first_accessed.access_order, second_accessed.access_order)
        self.assertEquals(
            copy_manager.expanded_server_attributes["common_key"],
            first_accessed.attribute_value,
        )

    def _create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        logs_json_array = []
        for entry in configuration_logs_entry:
            logs_json_array.append(entry)

        config = ScalyrTestUtils.create_configuration(
            extra_toplevel_config={"logs": logs_json_array}
        )

        self.__monitor_fake_instances = []
        for monitor_log_config in monitors_log_configs:
            self.__monitor_fake_instances.append(FakeMonitor(monitor_log_config))

        # noinspection PyTypeChecker
        return CopyingManager(config, self.__monitor_fake_instances)
