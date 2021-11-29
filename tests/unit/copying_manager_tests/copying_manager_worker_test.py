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
from __future__ import unicode_literals

import time
import threading
import platform
import mock
import sys

if False:
    from typing import Tuple
    from typing import Optional
    from typing import Dict


import pytest

from scalyr_agent import __scalyr__
from scalyr_agent.test_base import skipIf
from tests.unit.copying_manager_tests.common import (
    TestableCopyingManagerWorkerSession,
    CopyingManagerCommonTest,
    TestEnvironBuilder,
    TestableCopyingManagerWorkerSessionProxy,
)

from scalyr_agent.copying_manager.worker import create_shared_object_manager
from scalyr_agent.configuration import Configuration
from tests.unit.copying_manager_tests.test_environment import TestableLogFile

from scalyr_agent.log_processing import LogMatcher, LogFileProcessor

from scalyr_agent import scalyr_logging


import six

str = six.text_type
from six.moves import range


log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_5)


def pytest_generate_tests(metafunc):
    if "worker_type" in metafunc.fixturenames:
        test_params = ["thread"]
        # if the OS is not Linux and python version > 2.7 then also do the multiprocess workers testing.
        # Windows and Mac systems can not work with multiprocess workers since their process method is 'spawn'
        # and the copying manager relies on 'fork'
        if __scalyr__.PLATFORM_TYPE == __scalyr__.PlatformType.LINUX and sys.version_info >= (2, 7):
            test_params.append("process")

        metafunc.parametrize("worker_type", test_params)


def skip_on_multiprocess_workers(f):
    def wrapper(self, *args, **kwargs):
        if self.use_multiprocessing_workers:
            pytest.skip("This test can not be done for multiprocessing worker.")
        else:
            return f(self, *args, **kwargs)

    return wrapper


class CopyingManagerWorkerTest(CopyingManagerCommonTest):
    @pytest.fixture(autouse=True)
    def setup(self, worker_type):
        self.use_multiprocessing_workers = worker_type == "process"
        super(CopyingManagerWorkerTest, self).setup()

        self._shared_object_manager = None

        self._recreate_shared_object_manager()

    def teardown(self):
        if self._instance is not None and self._instance.is_alive():
            self._instance.stop_worker_session()

        if self.use_multiprocessing_workers:
            self._shared_object_manager.shutdown()

        super(CopyingManagerWorkerTest, self).teardown()

    def _recreate_shared_object_manager(self):
        """
        Recreate and restart shared object manager to be able to fork and inherit changes done by the test cases.
        """
        if self.use_multiprocessing_workers:
            if self._shared_object_manager:
                self._shared_object_manager.shutdown()
            self._shared_object_manager = create_shared_object_manager(
                TestableCopyingManagerWorkerSession,
                TestableCopyingManagerWorkerSessionProxy,
            )
            self._shared_object_manager.start()

    def _create_worker_session(self):

        config = self._env_builder.config
        api_key_config = self._env_builder.config.worker_configs[0]
        worker_id = "0"

        if self.use_multiprocessing_workers:
            # pylint: disable=E1101
            worker = self._shared_object_manager.create_worker_session(
                config, api_key_config, worker_id
            )
            # pylint: enable=E1101
        else:
            worker = TestableCopyingManagerWorkerSession(
                config, api_key_config, worker_id
            )

        return worker

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

        config_initial_data = {
            "workers": [{"workers": 1}],
            "use_multiprocessing_workers": self.use_multiprocessing_workers,
            "disable_send_requests": True,
            "disable_max_send_rate_enforcement_overrides": True,
            "pipeline_threshold": pipeline_threshold,
        }

        if config_data is not None:
            config_initial_data.update(config_data)

        self._env_builder = TestEnvironBuilder()

        self._env_builder.init_agent_dirs()

        self._env_builder.init_config(config_data)

        self._env_builder.config.disable_flow_control = disable_flow_control

    def _init_worker_instance(
        self,
        log_files_number=1,
        auto_start=True,
        add_processors=True,
        use_pipelining=False,
        disable_flow_control=False,
    ):  # type: (int, bool, bool, bool, bool) -> Tuple[Tuple[TestableLogFile], TestableCopyingManagerWorkerSession]

        if self._env_builder is None:
            self._init_test_environment(
                log_files_number=log_files_number,
                use_pipelining=use_pipelining,
                disable_flow_control=disable_flow_control,
            )

        if log_files_number is not None:
            test_files = self._env_builder.recreate_files(  # type: ignore
                log_files_number, self._env_builder.non_glob_logs_dir  # type: ignore
            )
        else:
            test_files = tuple()

        self._instance = self._create_worker_session()

        if add_processors:
            for test_file in test_files:
                self._spawn_single_log_processor(test_file)

        if auto_start:
            self._instance.start_worker_session()

        return test_files, self._instance  # type: ignore

    def _spawn_single_log_processor(
        self,
        log_file,
        checkpoints=None,
        copy_at_index_zero=False,
    ):
        # type: (TestableLogFile, Optional[Dict], bool)-> LogFileProcessor
        log_config = self._env_builder.get_log_config(log_file)  # type: ignore

        matcher = LogMatcher(self._env_builder.config, log_config)  # type: ignore
        if checkpoints is None:
            checkpoints = {}

        processors = matcher.find_matches(
            existing_processors=[],
            previous_state=checkpoints,
            copy_at_index_zero=copy_at_index_zero,
            create_log_processor=self._instance.create_and_schedule_new_log_processor,
        )

        return processors[0]


class TestsRunning(CopyingManagerWorkerTest):
    @pytest.mark.skipif(sys.version_info < (2, 7), reason="Skip for python < 2.7")
    @skip_on_multiprocess_workers
    def test_wait_copying(self):
        from concurrent.futures import ThreadPoolExecutor

        run_released = threading.Event()

        _, worker = self._init_worker_instance(1, auto_start=False)

        original_run = worker.run

        # create mock run method that can wait for signal to start
        def delayed_run():
            # we need to set this event to resume worker.
            run_released.wait()
            return original_run()

        with mock.patch.object(worker, "run", wraps=delayed_run):
            executor = ThreadPoolExecutor()

            worker.start_worker_session(stop_at=None)

            # wait for copying start in separate thread

            wait_future = executor.submit(worker.wait_for_copying_to_begin)

            # check for waiting is finished, it must not be finished until event is not set.
            assert not wait_future.done()

            run_released.set()

            # now waiting  should be finished.
            wait_future.result(timeout=3)
            assert wait_future.done()

    @pytest.mark.skipif(
        sys.version_info < (2, 7), reason="This test is not supported by python < 2.7"
    )
    @pytest.mark.timeout(10)
    def test_health_check_after_error(self):

        # mock the function which is called before the worker starts copying.

        def failing_init_scalyr_client(*args, **kwargs):
            raise RuntimeError("Expected error. Do not worry.")

        # mock class function with the failing one.
        # NOTE: in order to be able to mock function in multiprocess worker, we mock a class not an instance.
        with mock.patch.object(
            TestableCopyingManagerWorkerSession,
            "_init_scalyr_client",
            failing_init_scalyr_client,
        ):
            with mock.patch.object(
                Configuration,
                "healthy_max_time_since_last_copy_attempt",
                new_callable=mock.PropertyMock,
            ) as config_max_time_mock:
                # reduce the 'healthy_max_time_since_last_copy_attempt' option in the config to save the time
                config_max_time_mock.return_value = 0.01
                # recreate and start a new shared object manager to fork a process at the moment where functions are mocked.
                self._recreate_shared_object_manager()

                # NOTE: we have to disable flow control on worker
                # because it will just be deadlocked on the exception which we are raising.
                _, worker = self._init_worker_instance(
                    2, auto_start=False, disable_flow_control=True
                )

                worker.start_worker_session()
                worker.wait_for_copying_to_begin()

                # wait until worker is crashed.
                while worker.is_alive():
                    time.sleep(0.1)

                status = worker.generate_status()

                assert status.health_check_result != "Good"


class TestCopyingManagerWorkerProcessors(CopyingManagerWorkerTest):
    def test_without_log_processors(self):
        self._init_worker_instance(0)

        # do some full iterations of the worker without any log processors.
        for _ in range(10):
            assert self._wait_for_rpc_and_respond() == []

    def test_add_log_processors_before_start(self):
        (test_file, test_file2), worker = self._init_worker_instance(
            2, auto_start=False, add_processors=False
        )

        self._spawn_single_log_processor(test_file)
        self._spawn_single_log_processor(test_file2)

        assert len(worker.get_log_processors()) == 0

        worker.start_worker_session(
            stop_at=TestableCopyingManagerWorkerSession.SLEEPING
        )

        assert len(worker.get_log_processors()) == 2

        self._append_lines_and_check(["Hello"], log_file=test_file)
        self._append_lines_and_check(["Hello friend!"], log_file=test_file)
        self._append_lines_and_check(["Line1", "Line2", "Line3"], log_file=test_file)

        self._append_lines_and_check(["Hello"], log_file=test_file2)
        self._append_lines_and_check(["Hello friend!"], log_file=test_file2)
        self._append_lines_and_check(["Line1", "Line2", "Line3"], log_file=test_file2)

    def test_add_log_processors_after_start(self):
        (test_file, test_file2), worker = self._init_worker_instance(
            2, add_processors=False
        )

        assert len(worker.get_log_processors()) == 0

        worker.wait_for_full_iteration()

        # create processor from configuration and add it to worker.
        self._spawn_single_log_processor(test_file)
        self._spawn_single_log_processor(test_file2)

        worker.wait_for_full_iteration()

        assert len(worker.get_log_processors()) == 2

        with self.current_log_file(test_file):
            self._append_lines_and_check(["Hello"])
            self._append_lines_and_check(["Hello friend!"])
            self._append_lines_and_check(["Line1", "Line2", "Line3"])

        with self.current_log_file(test_file2):
            self._append_lines_and_check(["Hello"])
            self._append_lines_and_check(["Hello friend!"])
            self._append_lines_and_check(["Line1", "Line2", "Line3"])

    def test_add_and_remove_multiple_log_processors(self):
        (test_file, test_file2, test_file3), worker = self._init_worker_instance(
            3, add_processors=False
        )

        assert len(worker.get_log_processors()) == 0

        processor = self._spawn_single_log_processor(test_file)
        self._spawn_single_log_processor(test_file2)
        self._spawn_single_log_processor(test_file3)

        worker.perform_scan()

        assert len(worker.get_log_processors()) == 3

        with self.current_log_file(test_file):
            self._append_lines_and_check(["Hello"])
            self._append_lines_and_check(["Hello friend!"])
            self._append_lines_and_check(["Line1", "Line2", "Line3"])
        with self.current_log_file(test_file2):
            self._append_lines_and_check(["Hello"])
            self._append_lines_and_check(["Hello friend!"])
            self._append_lines_and_check(["Line1", "Line2", "Line3"])

        with self.current_log_file(test_file3):
            self._append_lines_and_check(["Hello"])
            self._append_lines_and_check(["Hello friend!"])
            self._append_lines_and_check(["Line1", "Line2", "Line3"])

        processor.close()

        worker.wait_for_full_iteration()

        test_file.append_lines("This line should not be in request.")
        test_file2.append_lines("This line is OK.")

        # get next request, it must not contain lines from deleted file.
        assert self._wait_for_rpc_and_respond() == ["This line is OK."]

        # add this file again

        self._spawn_single_log_processor(test_file)

        worker.perform_scan()

        with self.current_log_file(test_file):
            self._append_lines_and_check(
                ["This line is OK too now.", "This line is still OK."]
            )


class TestCopyingManagerWorkerStatus(CopyingManagerWorkerTest):
    def test_generate_status(self):
        (test_file,), worker = self._init_worker_instance()

        self._append_lines_and_check(["First line", "Second line"], log_file=test_file)

        status = worker.generate_status()

        assert len(status.log_processors) == 1

    def test_health_check_status(self):
        (test_file,), worker = self._init_worker_instance()

        worker.change_last_attempt_time(time.time())

        status = worker.generate_status()
        assert status.health_check_result == "Good"

    def test_health_check_status_failed(self):
        (test_file,), worker = self._init_worker_instance()

        # worker._CopyingManagerThreadedWorker__last_attempt_time = time.time() - (1000 * 65)
        worker.change_last_attempt_time(time.time() - (1000 * 65))

        status = worker.generate_status()
        assert (
            status.health_check_result
            == "Worker session '0' failed, max time since last copy attempt (60.0 seconds) exceeded"
        )


class TestCopyingManagerWorkerResponses(CopyingManagerWorkerTest):
    @skipIf(platform.system() == "Windows", "Skipping failing test on Windows")
    @skip_on_multiprocess_workers
    def test_stale_request(self):

        (test_file,), worker = self._init_worker_instance()

        test_file.append_lines("First line", "Second line")
        (lines, responder_callback) = self._wait_for_rpc()

        assert lines == ["First line", "Second line"]

        with mock.patch.object(self._env_builder.config, "max_retry_time", 0):

            # Set response to force copying manager to retry request.
            responder_callback("error")

            # Because of mocked time,repeated request will be rejected as too old.
            (lines, responder_callback) = self._wait_for_rpc()

            assert lines == []

    def test_normal_error(self):
        (test_file,), worker = self._init_worker_instance()

        test_file.append_lines("First line", "Second line")
        lines, responder_callback = self._wait_for_rpc()

        assert lines == ["First line", "Second line"]
        responder_callback("error")

        # previous response was - error, have to repeat previous lines.
        test_file.append_lines("Third line")
        lines, responder_callback = self._wait_for_rpc()

        assert lines == ["First line", "Second line"]
        responder_callback("success")

        lines, responder_callback = self._wait_for_rpc()
        assert lines == ["Third line"]
        responder_callback("success")

    def test_drop_request_due_to_error(self):
        (test_file,), worker = self._init_worker_instance()

        test_file.append_lines("First line", "Second line")
        lines, responder_callback = self._wait_for_rpc()

        assert lines == ["First line", "Second line"]
        responder_callback("discardBuffer")

        # must discard first two lines
        test_file.append_lines("Third line")
        lines, responder_callback = self._wait_for_rpc()
        assert lines == ["Third line"]
        responder_callback("success")

        lines, responder_callback = self._wait_for_rpc()
        assert len(lines) == 0
        responder_callback("success")

    def test_request_too_large_error(self):
        (test_file,), worker = self._init_worker_instance()

        test_file.append_lines("First line", "Second line")
        lines, responder_callback = self._wait_for_rpc()

        assert lines == ["First line", "Second line"]
        responder_callback("requestTooLarge")

        test_file.append_lines("Third line")
        lines, responder_callback = self._wait_for_rpc()

        assert lines == ["First line", "Second line", "Third line"]

    def __was_pipelined(self, request):
        return "pipelined=1.0" in request.get_timing_data()

    def test_pipelined_requests(self):
        (test_file,), worker = self._init_worker_instance(use_pipelining=True)

        test_file.append_lines("First line", "Second line")
        worker.perform_scan()
        test_file.append_lines("Third line")
        worker.perform_pipeline_scan()
        (request, responder_callback) = worker.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("success")

        (request, responder_callback) = worker.wait_for_rpc()

        assert self.__was_pipelined(request)
        lines = self._extract_lines(request)

        assert lines == ["Third line"]

        responder_callback("success")

    def test_pipelined_requests_with_processor_closes(self):
        # Tests bug related to duplicate log upload (CT-107, AGENT-425, CT-114)
        # The problem was related to mixing up the callbacks between two different log processors
        # during pipeline execution and one of the log processors had been closed.
        #
        # To replicate, we need to upload to two log files.
        (test_file, test_file2), worker = self._init_worker_instance(
            2, use_pipelining=True
        )

        test_file.append_lines("p_First line", "p_Second line")
        test_file2.append_lines("s_First line", "s_Second line")

        # Mark the primary log file to be closed (remove its log processor) once all current bytes have
        # been uploaded.
        worker.close_at_eof(str(test_file.path))

        worker.perform_scan()

        # Set up for the pipeline scan.  Just add a few more lines to the secondary file.
        test_file2.append_lines("s_Third line")
        worker.perform_pipeline_scan()
        (request, responder_callback) = worker.wait_for_rpc()
        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)
        assert len(lines) == 4
        assert lines == [
            "p_First line",
            "p_Second line",
            "s_First line",
            "s_Second line",
        ]

        responder_callback("success")

        # With the bug, at this point, the processor for the secondary log file has been removed.
        # We can tell this by adding more log lines to it and see they aren't copied up.  However,
        # we first have to read the request that was already created via pipelining.
        (request, responder_callback) = worker.wait_for_rpc()
        assert self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["s_Third line"]
        responder_callback("success")

        # Now add in more lines to the secondary.  If the bug was present, these would not be copied up.
        test_file2.append_lines("s_Fourth line")
        worker.perform_scan()

        (request, responder_callback) = worker.wait_for_rpc()

        assert not self.__was_pipelined(request)
        lines = self._extract_lines(request)

        assert lines == ["s_Fourth line"]
        responder_callback("success")

    def test_pipelined_requests_with_normal_error(self):
        (test_file,), worker = self._init_worker_instance(use_pipelining=True)
        test_file.append_lines("First line", "Second line")

        worker.perform_scan()
        test_file.append_lines("Third line")
        worker.perform_pipeline_scan()
        (request, responder_callback) = worker.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("error")

        (request, responder_callback) = worker.wait_for_rpc()
        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("success")

        (request, responder_callback) = worker.wait_for_rpc()

        assert self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["Third line"]

        responder_callback("success")

    def test_pipelined_requests_with_retry_error(self):
        (test_file,), worker = self._init_worker_instance(use_pipelining=True)
        test_file.append_lines("First line", "Second line")

        worker.perform_scan()
        test_file.append_lines("Third line")
        worker.perform_pipeline_scan()
        (request, responder_callback) = worker.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("requestTooLarge")

        (request, responder_callback) = worker.wait_for_rpc()
        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line", "Third line"]

        responder_callback("success")


class TestCopyingManagerWorkerCheckpoints(CopyingManagerWorkerTest):
    def test_checkpoints(self):
        (test_file,), worker = self._init_worker_instance()

        self._append_lines_and_check(["First line"], log_file=test_file)

        worker.stop_worker_session()

        checkpoints = self._env_builder.get_checkpoints(worker.get_id())["checkpoints"]

        assert test_file.str_path in checkpoints

        for path, state in checkpoints.items():
            assert (
                "time" in state
            ), "Checkpoint state for the file {} does not have required 'time' field.".format(
                path
            )

        # create new worker. Imitate second launch. Worker must start from beginning of the file.
        self._instance = worker = self._create_worker_session()
        self._spawn_single_log_processor(test_file, copy_at_index_zero=True)

        worker.start_worker_session(stop_at=TestableCopyingManagerWorkerSession.SENDING)
        worker.wait_for_copying_to_begin()

        test_file.append_lines("Second line")

        # should be the same first line again.
        assert self._wait_for_rpc_and_respond() == ["First line"]

        assert self._wait_for_rpc_and_respond() == ["Second line"]

        worker.stop_worker_session()

        checkpoints = self._env_builder.get_checkpoints(worker.get_id())["checkpoints"]
        assert test_file.str_path in checkpoints

        for path, state in checkpoints.items():
            assert (
                "time" in state
            ), "Checkpoint state for the file {} does not have required 'time' field.".format(
                path
            )

        # create new worker. Imitate third launch.
        # Now we also provide checkpoints from previous run, so it have to ignore "copy_at_index_zero".
        self._instance = worker = self._create_worker_session()
        processor = self._spawn_single_log_processor(
            test_file, checkpoints=checkpoints, copy_at_index_zero=True
        )

        worker.start_worker_session()

        test_file.append_lines("Third line")

        # should be third line
        assert self._wait_for_rpc_and_respond() == ["Third line"]

        # check if the collection of the checkpoints for the closed files is empty until some log processor is closed.
        assert worker.get_and_reset_closed_files_checkpoints() == {}

        # close log processor and check if its checkpoint in the collection for the closed processors.
        processor.close()
        worker.wait_for_full_iteration()
        closed_files_checkpoints = worker.get_and_reset_closed_files_checkpoints()

        for path, state in closed_files_checkpoints.items():
            assert (
                "time" in state
            ), "Checkpoint state for the file {} does not have required 'time' field.".format(
                path
            )

        assert processor.get_log_path() in closed_files_checkpoints
