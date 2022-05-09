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
# Those test just the same test from previous copying manager, but adapted to the new copying manager.
#

from __future__ import unicode_literals
from __future__ import absolute_import
from io import open


__author__ = "czerwin@scalyr.com"

import sys
import logging
import platform
import os
import re

import pytest

root = logging.getLogger()
root.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
root.addHandler(ch)

from scalyr_agent import scalyr_init
from scalyr_agent import util as scalyr_util

scalyr_init()

from scalyr_agent import scalyr_logging
from tests.unit.copying_manager_tests.copying_manager_new_test import CopyingManagerTest


log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_5)

import six


def pytest_generate_tests(metafunc):
    """
    Run all tests for each configuration.
    """
    if "worker_type" in metafunc.fixturenames:
        test_params = [["thread", 1, 1], ["thread", 2, 2]]
        # if the OS is not Windows / OSX and python version > 2.7 then also do the multiprocess workers testing.
        if platform.system() not in ["Windows", "Darwin"] and sys.version_info >= (
            2,
            7,
        ):
            test_params.extend([["process", 1, 1], ["process", 2, 2]])

        metafunc.parametrize(
            "worker_type, workers_count, worker_sessions_count", test_params
        )


def _add_non_utf8_to_checkpoint_file(path):
    """
    Add a unicode character to the checkpoint data stored in file located in "path"
    """
    fp = open(path, "r")
    data = scalyr_util.json_decode(fp.read())
    fp.close()
    # 2-> TODO json libraries do not allow serialize bytes string with invalid UTF-8(ujson)or even bytes in general(json).
    # so to test this case we must write non-utf8 byte directly, without serializing.

    # this string will be replaced with invalid utf8 byte after encoding.
    data["test"] = "__replace_me__"

    json_string = scalyr_util.json_encode(data, binary=True)

    # replace prepared substring to invalid byte.
    json_string = json_string.replace(b"__replace_me__", b"\x96")

    fp = open(path, "wb")
    fp.write(json_string)
    fp.close()


def _write_bad_checkpoint_file(path):
    """
    Write invalid JSON in file located in "path"
    """
    fp = open(path, "w")
    fp.write(scalyr_util.json_encode("}data{,:,,{}"))
    fp.close()


class TestCopyingManagerEnd2End(CopyingManagerTest):
    """
    Initially, those tests were created for the unittest library,
    and they are were ported to work on pytest in order to be able to parametrize them to run tests for different
    copying manager configurations, such as muti-worker, multi-process workers.
    """

    # TODO: Remove those  methods and rewrite in pytest style.
    # region Those methods are needed to port unittest functions
    def __create_test_instance(
        self, root_dir=None, auto_start=True, use_pipelining=False
    ):
        if root_dir:
            files_number = None
        else:
            files_number = 1

        files, manager = self._init_manager(
            files_number, auto_start=auto_start, use_pipelining=use_pipelining
        )

        self._manager = manager

        if root_dir:
            return manager

        self._log_file1 = files[0]
        self.__test_log_file = self._log_file1.str_path

        self._config = self._env_builder.config

        return manager

    def __append_log_lines(self, *lines):
        self._log_file1.append_lines(*lines)

    def __extract_lines(self, request):
        return self._extract_lines(request)

    def assertEquals(self, expected, actual):
        assert expected == actual

    def assertTrue(self, expr):
        assert expr

    def assertFalse(self, expr):
        assert not expr

    def _file_contains_regex(self, file_path, expression):
        matcher = re.compile(expression)

        with open(file_path, "r") as fp:
            content = fp.read()

        return bool(matcher.search(content))

    def assertLogFileDoesntContainsRegex(self, expression, file_path_or_glob):
        """
        Custom assertion function which asserts that the provided log file path doesn't contain a
        string which matches the provided regular expression.

        This function performs checks against the whole file content which means it comes handy in
        scenarios where you need to perform cross line checks.

        :param file_path_or_glob: Path or glob.
        """

        file_paths = scalyr_util.match_glob(file_path_or_glob)

        for file_path in file_paths:
            if self._file_contains_regex(file_path=file_path, expression=expression):
                with open(file_path, "r") as fp:
                    content = fp.read()

                self.__assertion_failed = True
                pytest.fail(
                    'File "%s" contains "%s" expression, but it shouldn\'t.\n\nActual file content: %s'
                    % (file_path, expression, content)
                )

    def assertLogFileContainsRegex(self, expression, file_path_or_glob):
        """
        Custom assertion function which asserts that the provided log file path contains a string
        which matches the provided regular expression.

        This function performs checks against the whole file content which means it comes handy in
        scenarios where you need to perform cross line checks.

        :param expression: Regular expression to match against the whole file content.
        :param file_path_or_glob: Path or glob
        """

        file_paths = scalyr_util.match_glob(file_path_or_glob)

        for file_path in file_paths:
            if self._file_contains_regex(file_path=file_path, expression=expression):
                break

        else:
            pytest.fail(
                'File "%s" does not contain "%s" expression.'
                % (file_path_or_glob, expression)
            )

    # endregion

    def test_single_log_file(self):
        manager = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = manager.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("success")

    def test_multiple_scans_of_log_file(self):
        controller = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("success")

        self.__append_log_lines("Third line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals("Third line", lines[0])

    def test_normal_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("error")

        self.__append_log_lines("Third line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

    def test_drop_request_due_to_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("discardBuffer")

        self.__append_log_lines("Third line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals("Third line", lines[0])

    def test_retry_request_due_to_parse_failure(self):
        controller = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("parseResponseFailed")

        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

    def test_request_too_large_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("requestTooLarge")

        self.__append_log_lines("Third line")
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(3, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])
        self.assertEquals("Third line", lines[2])

    def test_pipelined_requests(self):
        if self.worker_sessions_count * self.workers_count > 1:
            pytest.skip("This test works only on one worker configuration.")

        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines("First line", "Second line")

        controller.perform_scan()
        self.__append_log_lines("Third line")
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("success")

        (request, responder_callback) = controller.wait_for_rpc()

        self.assertTrue(self.__was_pipelined(request))

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals("Third line", lines[0])

        responder_callback("success")

    def test_pipelined_requests_with_normal_error(self):
        if self.worker_sessions_count * self.workers_count > 1:
            pytest.skip("This test works only on one worker configuration.")
        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines("First line", "Second line")

        controller.perform_scan()
        self.__append_log_lines("Third line")
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("error")

        (request, responder_callback) = controller.wait_for_rpc()
        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("success")

        (request, responder_callback) = controller.wait_for_rpc()

        self.assertTrue(self.__was_pipelined(request))

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals("Third line", lines[0])

        responder_callback("success")

    def test_pipelined_requests_with_retry_error(self):
        if self.worker_sessions_count * self.workers_count > 1:
            pytest.skip("This test works only on one worker configuration.")
        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines("First line", "Second line")

        controller.perform_scan()
        self.__append_log_lines("Third line")
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        responder_callback("requestTooLarge")

        (request, responder_callback) = controller.wait_for_rpc()
        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(3, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])
        self.assertEquals("Third line", lines[2])

        responder_callback("success")

    def test_start_from_full_checkpoint(self):
        controller = self.__create_test_instance()
        previous_root_dir = os.path.dirname(self.__test_log_file)

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        # stop thread on manager to write checkouts to file.
        controller.stop_manager()

        # write some new lines to log.
        self.__append_log_lines("Third line", "Fourth line")

        # Create new copying manager, but passing previous directory with same log and checkouts.
        # Also starting it manually, to not miss the first "SENDING" state.
        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )

        self._manager.start_manager()

        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        # thread should continue from saved checkpoint
        self.assertEquals(2, len(lines))
        self.assertEquals("Third line", lines[0])
        self.assertEquals("Fourth line", lines[1])

        # stopping one more time, but now emulating that checkpoint files are stale.
        controller.stop_manager()

        # This lines should be skipped by  copying manager.
        self.__append_log_lines("Fifth line", "Sixth line")

        # shift time on checkpoint files to make it seem like the checkpoint was written in the past.
        for worker in self._manager.worker_sessions:
            (
                checkpoints,
                active_chp,
            ) = worker.get_checkpoints()
            checkpoints["time"] -= self._config.max_allowed_checkpoint_age + 1
            active_chp["time"] -= self._config.max_allowed_checkpoint_age + 1
            worker.write_checkpoints(worker.get_checkpoints_path(), checkpoints)
            worker.write_checkpoints(worker.get_active_checkpoints_path(), active_chp)

        # also shift time in the consolidated checkpoint file.
        checkpoints = self._manager.consolidated_checkpoints
        checkpoints["time"] -= self._config.max_allowed_checkpoint_age + 1
        self._manager.write_consolidated_checkpoints(checkpoints)

        # create and manager.
        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )
        self._manager.start_manager()

        # We are expecting that copying manager has considered checkpoint file as stale,
        # and has skipped "fifth" and "sixth" lines.
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)
        self.assertEquals(0, len(lines))

    def test_start_from_active_checkpoint(self):
        controller = self.__create_test_instance()
        previous_root_dir = os.path.dirname(self.__test_log_file)

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        controller.stop_manager()

        # remove the checkpoints file, which should be only one,
        # because it has to clean all other files on stop. From this moment, all checkpoint states are removed
        os.remove(os.path.join(self._config.agent_data_path, "checkpoints.json"))

        # "active_checkpoints" file is used if it is newer than "full_checkpoints",
        # so we read "full_checkpoints" ...

        for worker in self._manager.worker_sessions:
            checkpoints, active_checkpoints = worker.get_checkpoints()

            # ... and make bigger(fresher) time value for "active_checkpoints".
            active_checkpoints["time"] = checkpoints["time"] + 1
            worker.write_checkpoints(worker.get_checkpoints_path(), checkpoints)
            worker.write_checkpoints(
                worker.get_active_checkpoints_path(), active_checkpoints
            )

        self.__append_log_lines("Third line", "Fourth line")

        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )

        self._manager.start_manager()

        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("Third line", lines[0])
        self.assertEquals("Fourth line", lines[1])

    def test_start_without_active_checkpoint(self):
        controller = self.__create_test_instance()
        previous_root_dir = os.path.dirname(self.__test_log_file)

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        controller.stop_manager()

        self.__append_log_lines("Third line", "Fourth line")

        # remove the checkpoints file, which should be only one,
        # because it has to clean all other files on stop. From this moment, all checkpoint states are removed
        os.remove(os.path.join(self._config.agent_data_path, "checkpoints.json"))

        for worker in self._manager.worker_sessions:
            # get preserved checkpoints from workers and write them ones more.
            # we do not write active-checkpoints because it is the purpose of this test.
            checkpoints, _ = worker.get_checkpoints()
            worker.write_checkpoints(worker.get_checkpoints_path(), checkpoints)

        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )
        self._manager.start_manager()
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals("Third line", lines[0])
        self.assertEquals("Fourth line", lines[1])

    def test_start_with_bad_checkpoint(self):
        # Check totally mangled checkpoint file in the form of invalid JSON, should be treated as not having one at all
        controller = self.__create_test_instance()

        previous_root_dir = os.path.dirname(self.__test_log_file)

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])
        controller.stop_manager()

        self.__append_log_lines("Third line", "Fourth line")

        _write_bad_checkpoint_file(str(controller.consolidated_checkpoints_path))

        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )
        self._manager.start_manager()
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        # In the case of a bad checkpoint file, the agent should just pretend the checkpoint file does not exist and
        # start reading the logfiles from the end. In this case, that means lines three and four will be skipped.
        self.assertEquals(0, len(lines))

    def test_start_with_non_utf8_checkpoint(self):
        # Check checkpoint file with invalid UTF-8 in it, should be treated the same as not having one at all
        controller = self.__create_test_instance()
        previous_root_dir = os.path.dirname(self.__test_log_file)

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])
        controller.stop_manager()

        self.__append_log_lines("Third line", "Fourth line")

        _add_non_utf8_to_checkpoint_file(str(controller.consolidated_checkpoints_path))

        controller = self.__create_test_instance(
            root_dir=previous_root_dir, auto_start=False
        )
        self._manager.start_manager()
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        # In the case of a bad checkpoint file, the agent should just pretend the checkpoint file does not exist and
        # start reading the logfiles from the end. In this case, that means lines three and four will be skipped.
        self.assertEquals(0, len(lines))

    def test_generate_status(self):
        controller = self.__create_test_instance()

        self.__append_log_lines("First line", "Second line")
        (request, responder_callback) = controller.wait_for_rpc()
        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals("First line", lines[0])
        self.assertEquals("Second line", lines[1])

        status = self._manager.generate_status()

        self.assertEquals(
            self._env_builder.MAX_NON_GLOB_TEST_LOGS + 1, len(status.log_matchers)
        )

        all_log_processors = {}

        # chech if each log file has its own log processor.
        for api_key_status in status.workers:
            for worker_status in api_key_status.sessions:
                for processor_status in worker_status.log_processors:
                    all_log_processors[processor_status.log_path] = processor_status

        for test_log in self._env_builder.current_test_log_files:
            assert test_log.str_path in all_log_processors

    def test_logs_initial_positions(self):
        controller = self.__create_test_instance(
            auto_start=False,
        )

        self.__append_log_lines(*"0123456789")

        # Start copying manager from 10 bytes offset.
        self._manager.start_manager(
            logs_initial_positions={self.__test_log_file: 5 * 2},
        )

        request, cb = controller.wait_for_rpc()

        lines = self.__extract_lines(request)

        self.assertEquals(["5", "6", "7", "8", "9"], lines)

    def test_whole_response_is_logged_on_non_success(self):
        statuses = ["discardBuffer", "requestTooLarge", "parseResponseFailed"]

        self._init_test_environment()

        for status in statuses:
            # Initially this long line shouldn't be present
            expected_body = (
                'Received server response with status="%s" and body: fake' % (status)
            )

            self.assertLogFileDoesntContainsRegex(
                expected_body,
                file_path_or_glob=os.path.join(
                    six.text_type(self._env_builder.agent_logs_path), "agent.*log"
                ),
            )

            controller = None
            try:
                controller = self.__create_test_instance()

                self.__append_log_lines("First line", "Second line")
                (request, responder_callback) = controller.wait_for_rpc()

                lines = self.__extract_lines(request)
                self.assertEquals(2, len(lines))
                self.assertEquals("First line", lines[0])
                self.assertEquals("Second line", lines[1])

                responder_callback(status)

                # But after response is received, it should be present
                expected_body = (
                    'Received server response with status="%s" and body: fake'
                    % (status)
                )
                self.assertLogFileContainsRegex(
                    expected_body,
                    file_path_or_glob=os.path.join(
                        six.text_type(self._env_builder.agent_logs_path),
                        "agent*_debug.log",
                    ),
                )
            finally:
                if controller:
                    controller.stop_manager()

    def __was_pipelined(self, request):
        return "pipelined=1.0" in request[0].get_timing_data()


class FakeMonitor(object):
    def __init__(self, monitor_log_config):
        self.module_name = "fake_monitor"
        self.log_config = monitor_log_config

    def set_log_watcher(self, log_watcher):
        pass

    def get_extra_server_attributes(self):
        return None


class FakeMonitor1(object):
    order = 0

    def __init__(self, monitor_log_config, id=None, attribute_key="extra_attrib"):
        self.id = id
        self.module_name = "fake_monitor_%s" % id
        self.log_config = monitor_log_config
        self.access_order = None
        self.attribute_key = attribute_key

    def set_log_watcher(self, log_watcher):
        pass

    @property
    def attribute_value(self):
        return "VALUE_%s" % self.id

    def get_extra_server_attributes(self):
        self.access_order = FakeMonitor1.order
        FakeMonitor1.order += 1
        return {self.attribute_key: self.attribute_value}
