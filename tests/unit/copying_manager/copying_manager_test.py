from __future__ import unicode_literals
from __future__ import absolute_import

if False:
    from typing import Dict
    from typing import Tuple

from tests.unit.copying_manager.config_builder import TestableLogFile
from scalyr_agent import scalyr_logging

from tests.unit.copying_manager.common import (
    CopyingManagerCommonTest,
    TestableCopyingManager,
    TestableCopyingManagerInterface,
)

log = scalyr_logging.getLogger(__name__)


class CopyingManagerTest(CopyingManagerCommonTest):
    def _create_manager_instanse(
        self,
        log_files_number=1,
        auto_start=True,
        use_pipelining=False,
        config_data=None,
    ):  # type: (int, bool, bool, Dict) -> Tuple[Tuple[TestableLogFile, ...], TestableCopyingManager]
        self._create_config(
            log_files_number=log_files_number,
            use_pipelining=use_pipelining,
            config_data=config_data,
        )
        self._instance = TestableCopyingManager(self._config_builder.config, [])

        if auto_start:
            self._instance.start_manager()
            self._instance.run_and_stop_at(TestableCopyingManagerInterface.SLEEPING)

        test_files = tuple(self._config_builder.log_files.values())
        return test_files, self._instance


class Test(CopyingManagerTest):
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

        self._instance = manager = TestableCopyingManager(
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

        self._config_builder.get_checkpoints_path("0").unlink()
        self._config_builder.get_active_checkpoints_path("0").unlink()

        self._instance = manager = TestableCopyingManager(
            self._config_builder.config, []
        )

        manager.start_manager()

        assert self._wait_for_rpc_and_respond() == []

        test_file.append_lines("Line7")
        test_file.append_lines("Line8")

        assert self._wait_for_rpc_and_respond() == ["Line7", "Line8"]
