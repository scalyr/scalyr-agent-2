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
import shutil
import os
import platform
import sys
from six.moves import range


if False:
    from typing import Dict
    from typing import Tuple

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib
import pytest

from scalyr_agent import scalyr_logging

from tests.unit.sharded_copying_manager_tests.common import (
    CopyingManagerCommonTest,
    TestableCopyingManager,
    TestableCopyingManagerFlowController,
    TestableLogFile,
    TestEnvironBuilder,
)

import six

log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_0)


def pytest_generate_tests(metafunc):
    """
    Run all tests for each configuration.
    """
    if "worker_type" in metafunc.fixturenames:
        test_params = [["thread", 1, 1], ["thread", 2, 2]]
        # if the OS is not Windows and python version > 2.7 then also do the multiprocess workers testing.
        if platform.system() != "Windows" and sys.version_info > (2, 6):
            test_params.extend([["process", 1, 1], ["process", 2, 2]])

        metafunc.parametrize("worker_type, api_keys_count, workers_count", test_params)


class CopyingManagerTest(CopyingManagerCommonTest):
    @pytest.fixture(autouse=True)
    def setup(self, worker_type, api_keys_count, workers_count):
        super(CopyingManagerTest, self).setup()
        self.use_multiprocessing_workers = worker_type == "process"
        self.api_keys_count = api_keys_count
        self.workers_count = workers_count

    def teardown(self):
        if self._instance is not None:
            self._instance.stop_manager()

            self._instance.cleanup()
        super(CopyingManagerTest, self).teardown()

    def _init_test_environment(
        self,
        log_files_number=1,
        use_pipelining=False,
        config_data=None,
        disable_flow_control=False,
    ):
        pipeline_threshold = 1.1
        if use_pipelining:
            pipeline_threshold = 0.0

        if config_data is None:
            config_data = {}

        if "api_keys" not in config_data:
            api_keys = []
            for i in range(self.api_keys_count):
                api_key_config = {"id": six.text_type(i), "workers": self.workers_count}
                if i > 0:
                    api_key_config["api_key"] = "<key_%s>" % i
                api_keys.append(api_key_config)
            config_data["api_keys"] = api_keys

        config_data[
            "use_multiprocess_copying_workers"
        ] = self.use_multiprocessing_workers
        config_data["disable_max_send_rate_enforcement_overrides"] = True
        config_data["pipeline_threshold"] = pipeline_threshold

        test_files, self._env_builder = TestEnvironBuilder.create_with_n_files(
            log_files_number, config_data=config_data
        )

        self._env_builder.config.disable_flow_control = disable_flow_control

    def _create_manager_instanse(
        self,
        log_files_number=1,
        auto_start=True,
        use_pipelining=False,
        config_data=None,
        disable_flow_control=False,
    ):  # type: (int, bool, bool, Dict, bool) -> Tuple[Tuple[TestableLogFile, ...], TestableCopyingManager]

        self._init_test_environment(
            log_files_number=log_files_number,
            use_pipelining=use_pipelining,
            config_data=config_data,
        )

        if self._env_builder is None:
            self._init_test_environment(
                log_files_number=log_files_number,
                config_data=config_data,
                disable_flow_control=disable_flow_control,
            )

        self._instance = TestableCopyingManager(self._env_builder.config, [])

        if auto_start:
            self._instance.start_manager()
            self._instance.run_and_stop_at(
                TestableCopyingManagerFlowController.SLEEPING
            )

        test_files = tuple(self._env_builder.log_files.values())
        return test_files, self._instance


class TestBasic(CopyingManagerTest):
    def test_multiple_workers(self):

        _, manager = self._create_manager_instanse(2)

        assert len(manager.workers) == self.workers_count * self.api_keys_count

        worker_pids = set(worker.get_pid() for worker in manager.workers)

        if self.use_multiprocessing_workers:
            assert len(worker_pids) == self.workers_count * self.api_keys_count
            assert os.getpid() not in worker_pids
        else:
            # in case of non multiprocess workers, all workers has the same process id as the main process.
            assert worker_pids == set([os.getpid()])

    def test_generate_status(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)
        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        status = manager.generate_status()

        assert status.health_check_result == "Good"
        return

    def test_health_check_status(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        manager._CopyingManager__last_scan_attempt_time = time.time()

        status = manager.generate_status()
        assert status.health_check_result == "Good"

    def test_health_check_status_failed(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        manager._CopyingManager__last_scan_attempt_time = time.time() - (1000 * 65)

        status = manager.generate_status()
        assert (
            status.health_check_result
            == "Failed, max time since last scan attempt (60.0 seconds) exceeded"
        )

    def test_health_check_status_worker_failed(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        # get all workers and simulate their last attempt timeout.
        for worker in manager.workers:
            worker.change_last_attempt_time(time.time() - (1000 * 65))

        status = manager.generate_status()
        assert (
            status.health_check_result
            == "Some workers has failed, see below for more info."
        )

    def test_failed_health_check_status_and_failed_worker(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        manager._CopyingManager__last_scan_attempt_time = time.time() - (1000 * 65)

        # get all workers and simulate their last attempt timeout.
        for worker in manager.workers:
            worker.change_last_attempt_time(time.time() - (1000 * 65))

        status = manager.generate_status()
        assert (
            status.health_check_result
            == "Failed, max time since last scan attempt (60.0 seconds) exceeded\n"
            "Some workers has failed, see below for more info."
        )

    def test_checkpoints(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

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

        for checkpoint_path in pathlib.Path(
            self._env_builder.config.agent_data_path
        ).glob("*checkpoints*.json"):
            checkpoint_path.unlink()

        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        manager.start_manager()

        assert self._wait_for_rpc_and_respond() == []

        test_file.append_lines("Line9")
        test_file.append_lines("Line10")

        assert set(self._wait_for_rpc_and_respond()) == set(["Line9", "Line10"])

    def test_old_version_checkpoints(self):
        """
        Test if the copying manager is able to pick checkpoint from the older versions of the agent.
        """

        (test_file, test_file2), manager = self._create_manager_instanse(2)

        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        manager.stop_manager()

        # write new lines, those lines should be send because of the checkpoints.
        test_file.append_lines("line3")
        test_file2.append_lines("line4")

        # get any worker and copy its checkpoints to the "<agent_dir>/data.checkpoints.json".
        #
        worker = manager.workers[-1]

        old_checkpoints_path = os.path.join(
            self._env_builder.config.agent_data_path, "checkpoints.json"
        )
        old_active_checkpoints_path = os.path.join(
            self._env_builder.config.agent_data_path, "active-checkpoints.json"
        )

        # move checkpoints files and rename tham as they were names in previous versions.
        shutil.move(str(worker.get_checkpoints_path()), old_checkpoints_path)
        shutil.move(
            str(worker.get_active_checkpoints_path()), old_active_checkpoints_path
        )

        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])
        manager.start_manager()

        # copying manager should read worker checkpoints from the new place.
        assert set(self._wait_for_rpc_and_respond()) == set(["line3", "line4"])

        # the checkpoint files from older versions of the agent have to be removed.
        assert not os.path.exists(old_checkpoints_path)
        assert not os.path.exists(old_active_checkpoints_path)

    def test_checkpoints_master_checkpoints(self):
        if self.workers_count == 1 and self.api_keys_count == 1:
            pytest.skip("This test is only for multi-worker copying manager.")

        (test_file, test_file2), manager = self._create_manager_instanse(2)

        # write something and stop in order to create checkpoint files.
        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert set(self._wait_for_rpc_and_respond()) == set(["line1", "line2"])

        manager.stop_manager()

        # recreate the manager, in order to simulate a new start.
        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        # start manager, it has to create master checkpoint file when starts.
        manager.start_manager()

        manager.stop()

        # add some new lines
        test_file.append_lines("line3")
        test_file2.append_lines("line4")

        # remove worker checkpoints, but files must not be skipped because of the
        for worker in manager.workers:
            os.unlink(str(worker.get_checkpoints_path()))
            os.unlink(str(worker.get_active_checkpoints_path()))

        # recreate the manager, in order to simulate a new start.
        self._instance = manager = TestableCopyingManager(self._env_builder.config, [])

        # start manager, it has to create master checkpoint file when starts.
        manager.start_manager()

        assert set(self._wait_for_rpc_and_respond()) == set(["line3", "line4"])
