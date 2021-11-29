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


import time
import os
import platform
import sys


if False:
    from typing import Dict
    from typing import Tuple

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib  # type: ignore

import pytest

from scalyr_agent import scalyr_logging
from scalyr_agent import __scalyr__

from tests.unit.copying_manager_tests.common import (
    CopyingManagerCommonTest,
    TestableCopyingManager,
    TestableCopyingManagerFlowController,
    TestableLogFile,
    TestEnvironBuilder,
    TestingConfiguration,
)

from scalyr_agent import util as scalyr_util

import six
from six.moves import range
import mock

log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_0)

# mock library does not have PropertyMock in python 2.6, so we just keep it None.
if sys.version_info >= (2, 7):
    PropertyMock = mock.PropertyMock
else:
    PropertyMock = None


def pytest_generate_tests(metafunc):
    """
    Run all tests for each configuration.
    """
    if "worker_type" in metafunc.fixturenames:
        test_params = [["thread", 1, 1], ["thread", 2, 2]]
        # if the OS is not Linux and python version > 2.7 then also do the multiprocess workers testing.
        # Windows and Mac systems can not work with multiprocess workers since their process method is 'spawn'
        # and the copying manager relies on 'fork'
        if __scalyr__.PLATFORM_TYPE == __scalyr__.PlatformType.LINUX and sys.version_info >= (2, 7):
            test_params.extend([["process", 1, 1], ["process", 2, 2]])

        metafunc.parametrize(
            "worker_type, workers_count, worker_sessions_count", test_params
        )


class CopyingManagerTest(CopyingManagerCommonTest):
    @pytest.fixture(autouse=True)
    def setup(self, worker_type, workers_count, worker_sessions_count):
        super(CopyingManagerTest, self).setup()
        self.use_multiprocessing_workers = worker_type == "process"
        self.workers_count = workers_count
        self.worker_sessions_count = worker_sessions_count

    def teardown(self):
        if self._instance is not None:
            self._instance.stop_manager()

            self._instance.cleanup()

        super(CopyingManagerTest, self).teardown()

    def _init_test_environment(
        self,
        use_pipelining=False,
        config_data=None,
        disable_flow_control=False,
    ):
        pipeline_threshold = 1.1
        if use_pipelining:
            pipeline_threshold = 0.0

        if config_data is None:
            config_data = {}

        if "workers" not in config_data:
            workers = []
            for i in range(self.workers_count - 1):
                worker_config = {
                    "id": "key_id_%s" % i,
                    "api_key": "key_%s" % i,
                }
                workers.append(worker_config)
            config_data["workers"] = workers

        config_data["default_sessions_per_worker"] = self.worker_sessions_count
        config_data["use_multiprocess_workers"] = self.use_multiprocessing_workers
        config_data["disable_max_send_rate_enforcement_overrides"] = True
        config_data["pipeline_threshold"] = pipeline_threshold
        config_data["implicit_agent_log_collection"] = False

        self._env_builder = TestEnvironBuilder()

        self._env_builder.init_agent_dirs()

        self._env_builder.init_config(config_data)

        scalyr_logging.set_log_destination(
            use_disk=True,
            logs_directory=six.text_type(self._env_builder.config.agent_log_path),
            agent_log_file_path="agent.log",
            agent_debug_log_file_suffix="_debug",
        )

        scalyr_logging.__log_manager__.set_log_level(scalyr_logging.DEBUG_LEVEL_5)

        self._env_builder.config.disable_flow_control = disable_flow_control
        self._env_builder.config.skip_agent_log_change = False

    def _create_manager_instance(self, auto_start=True):
        self._instance = TestableCopyingManager(self._env_builder.config, [])

        if auto_start:
            self._instance.start_manager()
            self._instance.run_and_stop_at(
                TestableCopyingManagerFlowController.SLEEPING
            )

        return self._instance

    def _init_manager(
        self,
        log_files_number=1,
        auto_start=True,
        use_pipelining=False,
        config_data=None,
        disable_flow_control=False,
    ):  # type: (int, bool, bool, Dict, bool) -> Tuple[Tuple[TestableLogFile, ...], TestableCopyingManager]

        if self._env_builder is None:
            self._init_test_environment(
                use_pipelining=use_pipelining,
                config_data=config_data,
                disable_flow_control=disable_flow_control,
            )

        if log_files_number is not None:
            files = self._env_builder.recreate_files(  # type: ignore
                log_files_number, self._env_builder.non_glob_logs_dir  # type: ignore
            )
        else:
            files = tuple()
        manager = self._create_manager_instance(auto_start=auto_start)

        return files, manager  # type: ignore


class TestBasic(CopyingManagerTest):
    def test_multiple_workers(self):

        _, manager = self._init_manager(2)

        assert (
            len(manager.worker_sessions)
            == self.worker_sessions_count * self.workers_count
        )

        worker_pids = set(worker.get_pid() for worker in manager.worker_sessions)

        if self.use_multiprocessing_workers:
            assert len(worker_pids) == self.worker_sessions_count * self.workers_count
            assert os.getpid() not in worker_pids
        else:
            # in case of non multiprocess workers, all workers has the same process id as the main process.
            assert worker_pids == set([os.getpid()])

    def test_generate_status(self):
        (test_file, test_file2), manager = self._init_manager(2)
        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        status = manager.generate_status()

        assert status.health_check_result == "Good"
        return

    def test_health_check_status(self):
        (test_file, test_file2), manager = self._init_manager(2)

        manager._CopyingManager__last_scan_attempt_time = time.time()

        status = manager.generate_status()
        assert status.health_check_result == "Good"

    def test_health_check_status_failed(self):
        (test_file, test_file2), manager = self._init_manager(2)

        manager._CopyingManager__last_scan_attempt_time = time.time() - (1000 * 65)

        status = manager.generate_status()
        assert (
            status.health_check_result
            == "Failed, max time since last scan attempt (60.0 seconds) exceeded"
        )

    def test_health_check_status_worker_failed(self):
        (test_file, test_file2), manager = self._init_manager(2)

        # get all workers and simulate their last attempt timeout.
        for worker in manager.worker_sessions:
            worker.change_last_attempt_time(time.time() - (1000 * 65))

        status = manager.generate_status()

        if self.worker_sessions_count > 1 or self.workers_count > 1:
            assert status.worker_sessions_health_check == "Some workers have failed."
            assert status.health_check_result == "Good"
        else:
            assert (
                status.worker_sessions_health_check
                == "Worker session 'default-0' failed, max time since last copy attempt (60.0 seconds) exceeded"
            )
            assert status.health_check_result == "Good"

    def test_failed_health_check_status_and_failed_worker(self):
        (test_file, test_file2), manager = self._init_manager(2)

        manager._CopyingManager__last_scan_attempt_time = time.time() - (1000 * 65)

        # get all workers and simulate their last attempt timeout.
        for worker in manager.worker_sessions:
            worker.change_last_attempt_time(time.time() - (1000 * 65))

        status = manager.generate_status()

        if self.worker_sessions_count > 1 or self.workers_count > 1:
            assert status.worker_sessions_health_check == "Some workers have failed."
            assert (
                status.health_check_result
                == "Failed, max time since last scan attempt (60.0 seconds) exceeded"
            )
        else:
            assert (
                status.worker_sessions_health_check
                == "Worker session 'default-0' failed, max time since last copy attempt (60.0 seconds) exceeded"
            )
            assert (
                status.health_check_result
                == "Failed, max time since last scan attempt (60.0 seconds) exceeded"
            )

    def test_checkpoints(self):
        (test_file, test_file2), manager = self._init_manager(2)

        # also add non-copying manager related checkpoints files, to be sure that the copying manager does not
        # touch them. This emulates the case where some agent monitors also store their own state in checkpoint files
        # and we must not consolidate them with the worker checkpoints.
        monitor_checkpoint_file_names = [
            "windows-event-checkpoints.json",
            "docker-checkpoints.json",
            "journald-checkpoints.json",
        ]

        monitors_checkpoint_paths = {}

        for name in monitor_checkpoint_file_names:
            monitor_checkpoint_path = pathlib.Path(
                self._env_builder.config.agent_data_path, name
            )
            check_text = "{0}. Do not delete me, please.".format(name)
            # write some text to the monitor checkpoint files, just to verify that it is not changed later.
            monitors_checkpoint_paths[monitor_checkpoint_path] = check_text
            monitor_checkpoint_path.write_text(check_text)

        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        # stop the manager and write some lines.
        # When manager is stared, it should pick recent checkpoints and read those lines.
        manager.stop_manager()
        test_file.append_lines("Line3")
        test_file.append_lines("Line4")

        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        manager.start_manager()

        # make sure that the first lines are lines which were written before manager start
        assert set(self._wait_for_rpc_and_respond()) == set(["Line3", "Line4"])

        test_file.append_lines("Line5")
        test_file.append_lines("Line6")

        assert set(self._wait_for_rpc_and_respond()) == set(["Line5", "Line6"])

        manager.stop_manager()

        test_file.append_lines("Line7")
        test_file.append_lines("Line8")

        # make sure that all worker session checkpoint files are consolidated and removed.
        for worker_session in manager.worker_sessions:
            assert not worker_session.get_checkpoints_path().exists()
            assert not worker_session.get_active_checkpoints_path().exists()

        assert manager.consolidated_checkpoints_path.exists()
        manager.consolidated_checkpoints_path.unlink()

        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        manager.start_manager()

        assert self._wait_for_rpc_and_respond() == []

        test_file.append_lines("Line9")
        test_file.append_lines("Line10")

        assert set(self._wait_for_rpc_and_respond()) == set(["Line9", "Line10"])

        # verify if monitor checkpoint file is remaining untouched.
        for monitor_checkpoint_path, check_text in monitors_checkpoint_paths.items():
            assert monitor_checkpoint_path.exists()
            assert monitor_checkpoint_path.read_text() == check_text

    def test_checkpoints_consolidated_checkpoints(self):
        if self.worker_sessions_count == 1 and self.workers_count == 1:
            pytest.skip("This test is only for multi-worker copying manager.")

        (test_file, test_file2), manager = self._init_manager(2)

        # write something and stop in order to create checkpoint files.
        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        manager.stop_manager()

        # recreate the manager, in order to simulate a new start.
        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        # start manager, it has to create consolidated checkpoint file when starts.
        manager.start_manager()

        manager.stop()

        # add some new lines
        test_file.append_lines("line3")
        test_file2.append_lines("line4")

        checkpoint_files = scalyr_util.match_glob(
            six.text_type(manager.consolidated_checkpoints_path)
        )

        # verify that only one file remains and it is a consolidated file.
        assert checkpoint_files == [str(manager.consolidated_checkpoints_path)]

        # recreate the manager, in order to simulate a new start.
        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        # start manager, it has to create consolidated checkpoint file when starts.
        manager.start_manager()

        assert set(self._wait_for_rpc_and_respond()) == set(["line3", "line4"])

    @pytest.mark.skipif(
        sys.version_info < (2, 7),
        reason="This test case can not be run on python < 2.7",
    )
    @mock.patch.object(
        TestingConfiguration, "log_deletion_delay", new_callable=PropertyMock
    )
    @mock.patch.object(
        TestingConfiguration,
        "max_new_log_detection_time",
        new_callable=PropertyMock,
    )
    def test_log_processors_lifecycle(
        self, log_deletion_delay, max_new_log_detection_time
    ):

        # mock config values so we do not  need to wait for the next file scan.
        log_deletion_delay.return_value = -1
        # do the same to not wait when copying manager decides that file is deleted.
        max_new_log_detection_time.return_value = -1

        test_files, manager = self._init_manager(10)

        for i, test_file in enumerate(test_files):
            self._append_lines(["file_{}_line1".format(i)], log_file=test_file)

        assert manager.worker_sessions_log_processors_count == len(test_files)
        assert manager.matchers_log_processor_count == len(test_files)

        for log_file in test_files:
            log_file.remove()

        # 1) log processors perform file processing and close deleted files.
        manager.wait_for_full_iteration()
        # 2) Copying manager removes closed processors from its collection.
        manager.wait_for_full_iteration()
        # 3) Log matchers remove their log processors.
        manager.wait_for_full_iteration()

        # check if there are no log processors remaining inside workers and log matchers.
        assert manager.worker_sessions_log_processors_count == 0
        assert manager.matchers_log_processor_count == 0

        # crete log file back and see if log processors are created back too.
        for log_file in test_files:
            log_file.create()

        manager.wait_for_full_iteration()

        assert manager.worker_sessions_log_processors_count == len(test_files)
        assert manager.matchers_log_processor_count == len(test_files)

    @pytest.mark.skipif(
        sys.version_info < (2, 7),
        reason="This test case can not be run on python < 2.7",
    )
    @mock.patch.object(
        TestingConfiguration, "log_deletion_delay", new_callable=PropertyMock
    )
    @mock.patch.object(
        TestingConfiguration,
        "max_new_log_detection_time",
        new_callable=PropertyMock,
    )
    def test_log_processors_lifecycle_with_glob(
        self, log_deletion_delay, max_new_log_detection_time
    ):

        # mock config values so we do not need to wait for the next file scan.
        log_deletion_delay.return_value = -1
        # do the same to not wait when copying manager decides that file is deleted.
        max_new_log_detection_time.return_value = -1

        _, manager = self._init_manager(0)

        # create some matching files.
        files = self._env_builder.recreate_files(
            10, self._env_builder.non_glob_logs_dir
        )

        assert manager.worker_sessions_log_processors_count == 0
        assert manager.matchers_log_processor_count == 0

        # wait for copying manager adds log processors.
        manager.wait_for_full_iteration()

        # both workers and log log matches should contain new log processors.
        assert manager.worker_sessions_log_processors_count == len(files)
        assert manager.matchers_log_processor_count == len(files)

        self._env_builder.remove_files(self._env_builder.non_glob_logs_dir)

        # 1) log processors perform file processing and close deleted files.
        manager.wait_for_full_iteration()
        # 2) Copying manager removes closed processors from its collection.
        manager.wait_for_full_iteration()
        # 3) Log matchers remove their log processors.
        manager.wait_for_full_iteration()

        # check if there are no log processors remaining inside workers and log matchers.
        assert manager.worker_sessions_log_processors_count == 0
        assert manager.matchers_log_processor_count == 0

        # crete log file back and see if log processors are created back too.
        files = self._env_builder.recreate_files(
            10, self._env_builder.non_glob_logs_dir
        )

        manager.wait_for_full_iteration()

        assert manager.worker_sessions_log_processors_count == len(files)
        assert manager.matchers_log_processor_count == len(files)

    @pytest.mark.skipif(
        sys.version_info < (2, 7),
        reason="This test case can not be run on python < 2.7",
    )
    @mock.patch.object(
        TestingConfiguration, "log_deletion_delay", new_callable=PropertyMock
    )
    @mock.patch.object(
        TestingConfiguration,
        "max_new_log_detection_time",
        new_callable=PropertyMock,
    )
    def test_log_processors_lifecycle_with_dynamic_matchers(
        self, log_deletion_delay, max_new_log_detection_time
    ):

        # mock config values so we do not need to wait for the next file scan.
        log_deletion_delay.return_value = -1
        # do the same to not wait when copying manager decides that file is deleted.
        max_new_log_detection_time.return_value = -1

        _, manager = self._init_manager(0)

        # create directory which is unknown for the managers configuration
        logs_dir = self._env_builder.test_logs_dir / "dynamicaly-added-logs"
        logs_dir.mkdir()

        files = self._env_builder.recreate_files(10, logs_dir)

        for file in files:
            log_config = self._env_builder.config.parse_log_config(
                {"path": file.str_path}
            )
            manager.add_log_config("scheduled-deletion", log_config)

        assert manager.worker_sessions_log_processors_count == 0
        assert manager.matchers_log_processor_count == 0

        # wait for copying manager adds log processors.
        manager.wait_for_full_iteration()

        assert manager.worker_sessions_log_processors_count == len(files)
        assert manager.matchers_log_processor_count == len(files)

        self._env_builder.remove_files(logs_dir)

        # 1) log processors perform file processing and close deleted files.
        manager.wait_for_full_iteration()
        # 2) Copying manager removes closed processors from its collection.
        manager.wait_for_full_iteration()
        # 3) Log matchers remove their log processors.
        manager.wait_for_full_iteration()

        # check if there are no log processors remaining inside workers and log matchers.
        assert manager.worker_sessions_log_processors_count == 0
        assert manager.matchers_log_processor_count == 0

        # crete log file back and see if log processors are created back too.
        files = self._env_builder.recreate_files(10, logs_dir)

        manager.wait_for_full_iteration()

        assert manager.worker_sessions_log_processors_count == len(files)
        assert manager.matchers_log_processor_count == len(files)
