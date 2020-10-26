from __future__ import unicode_literals
from __future__ import absolute_import


import time
import shutil

if False:
    from typing import Dict
    from typing import Tuple

from tests.unit.copying_manager.config_builder import TestableLogFile
from scalyr_agent import scalyr_logging

from tests.unit.copying_manager.common import (
    CopyingManagerCommonTest,
    TestableShardedCopyingManager,
    TestableCopyingManagerInterface,
)

log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_0)


class CopyingManagerTest(CopyingManagerCommonTest):
    def _create_manager_instanse(
        self,
        log_files_number=1,
        auto_start=True,
        use_pipelining=False,
        config_data=None,
    ):  # type: (int, bool, bool, Dict) -> Tuple[Tuple[TestableLogFile, ...], TestableShardedCopyingManager]

        if config_data is None:
            config_data = {"api_keys": [{"workers": 2}, {"workers": 2, "api_key": "key"}]}

        self._create_config(
            log_files_number=log_files_number,
            use_pipelining=use_pipelining,
            config_data=config_data,
        )
        self._instance = TestableShardedCopyingManager(self._config_builder.config, [])

        if auto_start:
            self._instance.start_manager()
            self._instance.run_and_stop_at(TestableCopyingManagerInterface.SLEEPING)

        test_files = tuple(self._config_builder.log_files.values())
        return test_files, self._instance


class Test(CopyingManagerTest):
    def test_workers(self):

        config_data = {"api_keys": [{"workers": 3}, {"workers": 2, "api_key": "key"}]}

        (test_file, test_file2), manager = self._create_manager_instanse(
            2, config_data=config_data
        )

        assert len(manager.workers) == 5

    def test_file_distribution(self):
        pass

    def test_generate_status(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)
        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert self._wait_for_rpc_and_respond() == ["line1", "line2"]

        status = manager.generate_status()

        return

    def test_health_check_status(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        manager._ShardedCopyingManager__last_attempt_time = time.time()

        status = manager.generate_status()
        assert status.health_check_result == "Good"

    def test_health_check_status_failed(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        manager._ShardedCopyingManager__last_attempt_time = time.time() - (1000 * 65)

        status = manager.generate_status()
        assert status.health_check_result == "Failed, max time since last copy attempt (60.0 seconds) exceeded"

    def test_health_check_status_worker_failed(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        # get the first worker and simulate its last attempt timeout.
        worker = list(manager.workers)[0]
        worker._CopyingManagerWorker__last_attempt_time = time.time() - (1000 * 65)

        status = manager.generate_status()
        assert status.health_check_result == "Failed, some of workers have reached their timeout since their last copy attempt."

    def test_checkpoints(self):
        (test_file, test_file2), manager = self._create_manager_instanse(2)

        test_file.append_lines("line1")
        test_file2.append_lines("line2")

        assert self._wait_for_rpc_and_respond() == ["line1", "line2"]

        # stop the manager and write some lines.
        # When manager is stared, it should pick recent checkpoints and read those lines.
        manager.controller.stop()
        test_file.append_lines("Line3")
        test_file.append_lines("Line4")

        self._instance = manager = TestableShardedCopyingManager(
            self._config_builder.config, []
        )

        manager.start_manager()

        # make sure that the first lines are lines which were written before manager start
        assert self._wait_for_rpc_and_respond() == ["Line3", "Line4"]

        test_file.append_lines("Line5")
        test_file.append_lines("Line6")

        assert self._wait_for_rpc_and_respond() == ["Line5", "Line6"]

        manager.controller.stop()

        test_file.append_lines("Line7")
        test_file.append_lines("Line8")

        shutil.rmtree(str(self._config_builder.checkpoints_dir_path))

        self._instance = manager = TestableShardedCopyingManager(
            self._config_builder.config, []
        )

        manager.start_manager()

        assert self._wait_for_rpc_and_respond() == []

        test_file.append_lines("Line7")
        test_file.append_lines("Line8")

        assert self._wait_for_rpc_and_respond() == ["Line7", "Line8"]



from scalyr_agent.copying_manager import CopyingManagerWorker


class TestProcess(CopyingManagerTest):
    def test_2(self):
        self._create_config()
        worker = CopyingManagerWorker(self._config_builder.config, self._config_builder.config.api_key_configs[0], "0_0")


        worker.start_worker()
        worker.augment_user_agent_for_client_session('wewqeqw')
        s = worker.generate_status()
        return