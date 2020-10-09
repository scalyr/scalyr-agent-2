from __future__ import absolute_import
from __future__ import unicode_literals

import unittest
import tempfile
import json
import time
from contextlib import contextmanager

from six.moves import range

if False:
    from typing import Union
    from typing import Dict
    from typing import Optional
    from typing import List
    from typing import Tuple
    from typing import Callable
    from typing import Generator

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib

from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.configuration import Configuration
from scalyr_agent import test_util

from tests.unit.copying_manager.cm import TestableCopyingManagerWorker

from tests.unit.copying_manager.config_builder import ConfigBuilder, TestableLogFile

import six

str = six.text_type


class CopyingManagerWorkerTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super(CopyingManagerWorkerTest, self).__init__(*args, **kwargs)
        self._config_builder = None  # type: Optional[ConfigBuilder]
        self._worker = None  # type: Optional[TestableCopyingManagerWorker]
        self._test_file1 = None  # type: Optional[TestableLogFile]

        # variable used by 'current_log_file' context manager.
        self._current_log_file = None

    def setUp(self):
        self._config_builder = None
        self._worker = None
        self._test_file1 = None

    def tearDown(self):
        if self._worker is not None:
            self._worker.stop_worker(wait_on_join=True)

        if self._config_builder is not None:
            self._config_builder.clear()

    def _extract_lines(self, request):

        parsed_request = test_util.parse_scalyr_request(request.get_payload())

        lines = []

        if "events" in parsed_request:
            for event in parsed_request["events"]:
                if "attrs" in event:
                    attrs = event["attrs"]
                    if "message" in attrs:
                        lines.append(attrs["message"].strip())

        return lines

    def _create_worker_instance(
        self,
        log_files_number=1,
        auto_start=True,
        add_processors=True,
        use_pipelining=False,
    ):
        # type: (int, bool, bool, bool) -> Tuple[Tuple[TestableLogFile, ...], TestableCopyingManagerWorker]
        pipeline_threshold = 1.1
        if use_pipelining:
            pipeline_threshold = 0.0

        config_data = {
            "debug_level": 5,
            "disable_max_send_rate_enforcement_overrides": True,
            "pipeline_threshold": pipeline_threshold,
        }

        test_files, self._config_builder = ConfigBuilder.build_config_with_n_files(
            log_files_number, config_data=config_data
        )

        self._worker = TestableCopyingManagerWorker(self._config_builder.config)

        if add_processors:
            for test_file in test_files:
                processor = test_file.spawn_single_log_processor()
                self._worker.add_log_processor(processor)

        if auto_start:
            self._worker.start_worker()

        return test_files, self._worker

    def _append_lines(self, *lines, **kwargs):
        # type: (*str, **TestableLogFile) -> None
        log_file = kwargs.get(six.ensure_str("log_file"))
        if log_file is None:
            if self._current_log_file is not None:
                log_file = self._current_log_file
            else:
                raise RuntimeError("File is not specified.")

        log_file.append_lines(*lines)

    def _wait_for_rpc(self):
        (request, responder_callback) = self._worker.controller.wait_for_rpc()
        request_lines = self._extract_lines(request)
        return request_lines, responder_callback

    def _wait_for_rpc_and_respond(self, response="success"):
        (request_lines, responder_callback) = self._wait_for_rpc()
        responder_callback(response)

        return request_lines

    def _append_lines_with_with_callback(self, *lines, **kwargs):
        # type: (*str, **Dict[str, Union[str, TestableLogFile]]) -> Tuple[List[str], Callable]

        self._worker.run_and_stop_at(TestableCopyingManagerWorker.SLEEPING)

        self._append_lines(*lines, **kwargs)
        (request, responder_callback) = self._worker.controller.wait_for_rpc()
        request_lines = self._extract_lines(request)
        return request_lines, responder_callback

    def _append_lines_and_wait_for_rpc(self, *lines, **kwargs):
        # type: (*str, **Union[str, TestableLogFile]) -> List[str]
        """
        Append some lines to log file, wait for response and set response.
        :param lines: Previously appended lines fetched from request.
        :param kwargs:
        :return:
        """
        response = kwargs.pop("response", "success")

        # set worker into sleeping state, so it can process new lines and send them.
        self._worker.run_and_stop_at(TestableCopyingManagerWorker.SLEEPING)

        self._append_lines(*lines, **kwargs)
        request_lines = self._wait_for_rpc_and_respond(response)
        return request_lines

    def _append_lines_and_check(self, *lines, **kwargs):
        # type: (*str, **Union[str, TestableLogFile]) -> None
        """
        Appends line and waits for next rpc request
        and also verifies that lines from request are equal to input lines.
        """

        request_lines = self._append_lines_and_wait_for_rpc(*lines, **kwargs)
        assert list(lines) == request_lines

    @contextmanager
    def current_log_file(self, log_file):
        # type: (TestableLogFile) -> Generator[TestableLogFile]
        """
        Context manager for fast access to the selected log file.
        """

        self._current_log_file = log_file
        yield

        self._current_log_file = None


class CopyingManagerWorkerProcessorsTest(CopyingManagerWorkerTest):
    def test_without_log_processors(self):
        self._create_worker_instance(0)

        # do some full iterations of the worker without any log processors.
        for _ in range(10):
            assert self._wait_for_rpc_and_respond() == []

    def test_add_log_processors_before_start(self):
        (test_file, test_file2), worker = self._create_worker_instance(
            2, auto_start=False, add_processors=False
        )

        log_processor = test_file.spawn_single_log_processor()
        log_processor2 = test_file2.spawn_single_log_processor()

        worker.add_log_processor(log_processor)
        worker.add_log_processor(log_processor2)

        assert len(worker.log_processors) == 0

        worker.start_worker(stop_at=TestableCopyingManagerWorker.SLEEPING)

        assert len(worker.log_processors) == 2

        self._append_lines_and_check("Hello", log_file=test_file)
        self._append_lines_and_check("Hello friend!", log_file=test_file)
        self._append_lines_and_check("Line1", "Line2", "Line3", log_file=test_file)

        self._append_lines_and_check("Hello", log_file=test_file2)
        self._append_lines_and_check("Hello friend!", log_file=test_file2)
        self._append_lines_and_check("Line1", "Line2", "Line3", log_file=test_file2)

    def test_add_log_processors_after_start(self):
        (test_file, test_file2), worker = self._create_worker_instance(
            2, add_processors=False
        )

        assert len(worker.log_processors) == 0

        worker.controller.wait_for_full_iteration()

        # create processor from configuration and add it to worker.
        processor = test_file.spawn_single_log_processor()
        processor2 = test_file2.spawn_single_log_processor()

        worker.add_log_processor(processor)
        worker.add_log_processor(processor2)

        worker.controller.wait_for_full_iteration()

        assert len(worker.log_processors) == 2

        with self.current_log_file(test_file):
            self._append_lines_and_check("Hello")
            self._append_lines_and_check("Hello friend!")
            self._append_lines_and_check("Line1", "Line2", "Line3")

        with self.current_log_file(test_file2):
            self._append_lines_and_check("Hello")
            self._append_lines_and_check("Hello friend!")
            self._append_lines_and_check("Line1", "Line2", "Line3")

    def test_add_and_remove_multiple_log_processors(self):
        (test_file, test_file2, test_file3), worker = self._create_worker_instance(3)

        assert len(worker.log_processors) == 3

        with self.current_log_file(test_file):
            self._append_lines_and_check("Hello")
            self._append_lines_and_check("Hello friend!")
            self._append_lines_and_check("Line1", "Line2", "Line3")
        with self.current_log_file(test_file2):
            self._append_lines_and_check("Hello")
            self._append_lines_and_check("Hello friend!")
            self._append_lines_and_check("Line1", "Line2", "Line3")

        with self.current_log_file(test_file3):
            self._append_lines_and_check("Hello")
            self._append_lines_and_check("Hello friend!")
            self._append_lines_and_check("Line1", "Line2", "Line3")

        worker.remove_log_processor(test_file.str_path)

        worker.controller.wait_for_full_iteration()

        test_file.append_lines("This line should not be in request.")
        test_file2.append_lines("This line is OK.")

        # get next request, it must not contain lines from deleted file.
        assert self._wait_for_rpc_and_respond() == ["This line is OK."]

        # add this file again
        worker.add_log_processor(test_file.spawn_single_log_processor())
        worker.controller.wait_for_full_iteration()

        with self.current_log_file(test_file):
            self._append_lines_and_check(
                "This line is OK too now.", "This line is still OK."
            )


class CopyingManagerWorkerStatusTest(CopyingManagerWorkerTest):
    def test_generate_status(self):
        (test_file,), worker = self._create_worker_instance()

        self._append_lines_and_check("First line", "Second line", log_file=test_file)

        status = worker.generate_status()

        assert len(status.log_processors) == 1

    def test_health_check_status(self):
        (test_file,), worker = self._create_worker_instance()

        # worker._CopyingManagerWorker__last_attempt_time = time.time()

        status = worker.generate_status()
        assert status.health_check_result == "Good"

    def test_health_check_status_failed(self):
        (test_file,), worker = self._create_worker_instance()

        self._manager._CopyingManager__last_attempt_time = time.time() - (1000 * 65)

        status = self._manager.generate_status()
        self.assertEquals(
            status.health_check_result,
            "Failed, max time since last copy attempt (60.0 seconds) exceeded",
        )


class CopyingManagerWorkerResponsesTests(CopyingManagerWorkerTest):
    def test_normal_error(self):
        (test_file,), worker = self._create_worker_instance()

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
        (test_file,), worker = self._create_worker_instance()

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
        (test_file,), worker = self._create_worker_instance()

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
        (test_file,), worker = self._create_worker_instance(use_pipelining=True)

        test_file.append_lines("First line", "Second line")
        worker.controller.perform_scan()
        test_file.append_lines("Third line")
        worker.controller.perform_pipeline_scan()
        (request, responder_callback) = worker.controller.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("success")

        (request, responder_callback) = worker.controller.wait_for_rpc()

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
        (test_file, test_file2), worker = self._create_worker_instance(
            2, use_pipelining=True
        )

        test_file.append_lines("p_First line", "p_Second line")
        test_file2.append_lines("s_First line", "s_Second line")

        # Mark the primary log file to be closed (remove its log processor) once all current bytes have
        # been uploaded.
        worker.controller.close_at_eof(str(test_file.path))

        worker.controller.perform_scan()

        # Set up for the pipeline scan.  Just add a few more lines to the secondary file.
        test_file2.append_lines("s_Third line")
        worker.controller.perform_pipeline_scan()
        (request, responder_callback) = worker.controller.wait_for_rpc()
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
        (request, responder_callback) = worker.controller.wait_for_rpc()
        assert self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["s_Third line"]
        responder_callback("success")

        # Now add in more lines to the secondary.  If the bug was present, these would not be copied up.
        test_file2.append_lines("s_Fourth line")
        worker.controller.perform_scan()

        (request, responder_callback) = worker.controller.wait_for_rpc()

        assert not self.__was_pipelined(request)
        lines = self._extract_lines(request)

        assert lines == ["s_Fourth line"]
        responder_callback("success")

    def test_pipelined_requests_with_normal_error(self):
        (test_file,), worker = self._create_worker_instance(use_pipelining=True)
        test_file.append_lines("First line", "Second line")

        worker.controller.perform_scan()
        test_file.append_lines("Third line")
        worker.controller.perform_pipeline_scan()
        (request, responder_callback) = worker.controller.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("error")

        (request, responder_callback) = worker.controller.wait_for_rpc()
        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("success")

        (request, responder_callback) = worker.controller.wait_for_rpc()

        assert self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["Third line"]

        responder_callback("success")

    def test_pipelined_requests_with_retry_error(self):
        (test_file,), worker = self._create_worker_instance(use_pipelining=True)
        test_file.append_lines("First line", "Second line")

        worker.controller.perform_scan()
        test_file.append_lines("Third line")
        worker.controller.perform_pipeline_scan()
        (request, responder_callback) = worker.controller.wait_for_rpc()

        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line"]

        responder_callback("requestTooLarge")

        (request, responder_callback) = worker.controller.wait_for_rpc()
        assert not self.__was_pipelined(request)

        lines = self._extract_lines(request)

        assert lines == ["First line", "Second line", "Third line"]

        responder_callback("success")


class CopyingManagerWorkerCheckpointTests(CopyingManagerWorkerTest):
    def test_checkpoints(self):
        (test_file,), worker = self._create_worker_instance()

        self._append_lines_and_check("First line", log_file=test_file)

        worker.controller.stop()

        checkpoints = self._config_builder.checkpoints["checkpoints"]

        assert test_file.str_path in checkpoints

        # create new worker. Imitate second launch. Worker must start from beginning of the file.
        self._worker = worker = TestableCopyingManagerWorker(
            self._config_builder.config
        )
        log_processor = test_file.spawn_single_log_processor(copy_at_index_zero=True)
        worker.add_log_processor(log_processor)

        worker.start_worker(stop_at=TestableCopyingManagerWorker.SENDING)

        test_file.append_lines("Second line")

        # should be the same first line again.
        assert self._wait_for_rpc_and_respond() == ["First line"]

        assert self._wait_for_rpc_and_respond() == ["Second line"]

        worker.controller.stop()

        checkpoints = self._config_builder.checkpoints["checkpoints"]
        assert test_file.str_path in checkpoints

        # create new worker. Imitate third launch.
        # Now we also provide checkpoints from previous run, so it have to ignore "copy_at_index_zero".
        self._worker = worker = TestableCopyingManagerWorker(
            self._config_builder.config
        )
        log_processor = test_file.spawn_single_log_processor(
            checkpoints=checkpoints, copy_at_index_zero=True
        )
        worker.add_log_processor(log_processor)

        worker.start_worker()

        test_file.append_lines("Third line")

        # should be third line
        assert self._wait_for_rpc_and_respond() == ["Third line"]
