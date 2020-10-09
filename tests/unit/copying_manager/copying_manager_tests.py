from __future__ import unicode_literals
from __future__ import absolute_import

import unittest
import time


import mock

from tests.unit.copying_manager.config_builder import ConfigBuilder
from scalyr_agent import scalyr_logging

from tests.unit.copying_manager.common import CopyingManagerCommonTest, TestableCopyingManagerWorker, \
    TestableCopyingManager

log = scalyr_logging.getLogger(__name__)


class CopyingManagerTest(CopyingManagerCommonTest):
    def _create_manager_instanse(
        self,
        log_files_number=1,
        auto_start=True,
        use_pipelining=False,
    ):  # type: (int, bool, bool) -> Tuple[Tuple[TestableLogFile, ...], TestableCopyingManager])
        self._create_config(
            log_files_number=log_files_number, use_pipelining=use_pipelining
        )
        self._instance = TestableCopyingManager(self._config_builder.config, [])

        if auto_start:
            self._instance.start_manager()

        test_files = tuple(self._config_builder.log_files.values())
        return test_files, self._instance


class Test(CopyingManagerTest):
    def test(self):
        (test_file,), manager = self._create_manager_instanse()

        test_file.append_lines("Hello")

        test_file.append_lines("Hello")

        lines, rc  = self._wait_for_rpc()

        rc("success")

        test_file.append_lines("Hello")

        lines, rc = self._wait_for_rpc()



        rc("success")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")

        return

    def test2(self):
        config_builder = ConfigBuilder()

        test_file = config_builder.add_log_file()

        config_builder.initialize()

        # with mock.patch("tests.unit.copying_manager.cm.CopyingManager", TestableCopyingManagerWorker):

        manager = TestableCopyingManager(config_builder.config, [])

        manager.start_manager()

        test_file.append_lines("Hello")

        test_file.append_lines("Hello")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")

        test_file.append_lines("Hello")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")

        r, rc = manager.controller.wait_for_rpc()

        rc("success")
        return
