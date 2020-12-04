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
from __future__ import print_function


import threading
import time
import itertools
import json
import os
import multiprocessing.managers

from contextlib import contextmanager

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib

if False:
    from typing import Optional
    from typing import Dict
    from typing import Union
    from typing import Tuple
    from typing import Callable
    from typing import Generator
    from typing import List
    from typing import Set

import mock

from scalyr_agent import test_util
from tests.unit.copying_manager_tests.test_environment import (
    TestEnvironBuilder,
    TestableLogFile,
    TestingConfiguration,
)

from scalyr_agent.copying_manager import copying_manager
from scalyr_agent.copying_manager import (
    CopyingManager,
    ApiKeyWorkerPool,
    CopyingManagerThreadedWorker,
)
from scalyr_agent.copying_manager.worker import (
    WORKER_PROXY_EXPOSED_METHODS,
    create_shared_object_manager,
)

from scalyr_agent.scalyr_client import AddEventsRequest
from scalyr_agent.log_processing import LogMatcher

import six


def extract_lines_from_request(request):
    # type: (Union[AddEventsRequest, List[AddEventsRequest]]) -> Union[List[six.text_type],Set[six.text_type]]
    """Extract lines from AddEventsRequest"""
    result = list()

    # if we test ShardedCopyingManager, it returns multiple requests for each of its workers,
    if isinstance(request, (list, tuple)):
        for req in request:
            lines = extract_lines_from_request(req)
            result.append(lines)

        return list(itertools.chain(*result))

    # extract single request.
    parsed_request = test_util.parse_scalyr_request(request.get_payload())

    lines = []

    if "events" in parsed_request:
        for event in parsed_request["events"]:
            if "attrs" in event:
                attrs = event["attrs"]
                if "message" in attrs:
                    lines.append(attrs["message"].strip())

    return lines


class CopyingManagerCommonTest(object):
    """
    Test case with many helpful features for CopyingManager and CopyingManagerWorker testing.
    """

    def setup(self):
        self._env_builder = None  # type: Optional[TestEnvironBuilder]
        self._instance = None

    def teardown(self):
        if self._env_builder is not None:
            self._env_builder.clear()

    def _extract_lines(self, request):
        return extract_lines_from_request(request)

    def _append_lines(self, lines, log_file=None):
        # type: (List[six.text_type], Optional[TestableLogFile]) -> None
        if log_file is None:
            if self._current_log_file is not None:
                log_file = self._current_log_file
            else:
                raise RuntimeError("File is not specified.")

        log_file.append_lines(*lines)

    def _wait_for_rpc(self):
        """
        Wraps the next 'self._manager.controller.wait_for_rpc()
        and returns lines instead' of requests.
        """
        (request, responder_callback) = self._instance.wait_for_rpc()
        request_lines = self._extract_lines(request)
        return request_lines, responder_callback

    def _wait_for_rpc_and_respond(self, response="success"):
        # type: (six.text_type) -> List
        """
        Wraps the next 'self._manager.controller.wait_for_rpc(), returns lines instead' of requests alongside with
        response  callback.
        :param response: response for request.
        """
        (request_lines, responder_callback) = self._wait_for_rpc()
        responder_callback(response)

        return request_lines

    def _append_lines_and_wait_for_rpc(self, lines, log_file=None, response="success"):
        # type: (List[six.text_type], Optional[TestableLogFile], six.text_type) -> List[str]
        """
        Append some lines to log file, wait for response and set response.
        :param lines: Previously appended lines fetched from request.
        :param kwargs:
        :return:
        """

        # set worker into sleeping state, so it can process new lines and send them.
        self._instance.run_and_stop_at(TestableCopyingManagerThreadedWorker.SLEEPING)

        self._append_lines(lines, log_file=log_file)
        request_lines = self._wait_for_rpc_and_respond(response)
        return request_lines

    def _append_lines_and_check(self, lines, log_file=None):
        # type: (List[six.text_type], Optional[TestableLogFile]) -> None
        """
        Appends line and waits for next rpc request
        and also verifies that lines from request are equal to input lines.
        """

        request_lines = self._append_lines_and_wait_for_rpc(lines, log_file=log_file)
        assert list(lines) == request_lines

    @contextmanager
    def current_log_file(self, log_file):
        # type: (TestableLogFile) -> Generator[TestableLogFile]
        """
        Context manager for fast access to the selected log file.
        """

        self._current_log_file = log_file
        yield self._current_log_file

        self._current_log_file = None


class TestableCopyingManagerFlowController:
    """
    This abstraction is used to allow for end-to-end testing of the CopyingManagerWorker and the CopyingManager itself.
    It is nothing more than set of common members that will be inherited by TestableCopyingWorker and TestableCopyingManager.
    For more info, please see the appropriate subclasses.
    """

    __test__ = False

    # The different points at which the CopyingManagerWorker can be stopped.  See below.
    SLEEPING = "SLEEPING"
    SENDING = "SENDING"
    RESPONDING = "RESPONDING"

    # To prevent tests from hanging indefinitely, wait a maximum amount of time before giving up on some test condition.
    WAIT_TIMEOUT = 5.0

    def __init__(self, configuration):
        # type: (TestingConfiguration) -> None

        # This cv protects all of the variables written by the CopyingManager thread.
        self._test_state_cv = threading.Condition()
        # Which state the CopyingManager or Worker should block in -- "sleeping", "sending", "responding"
        # We initialize it to a special value "all" so that it stops as soon the CopyingManager starts up.
        self._test_stop_state = "all"

        # If not none, a state the test must pass through before it tries to stop at `__test_stop_state`.
        # If this transition is not observed by the time it does get to the stop state, an assertion is thrown.
        self._test_required_transition = None
        # Whether or not the CopyingManager is stopped at __test_stop_state.
        self._test_is_stopped = False

        self._pending_response = None
        self._captured_request = None

        self._disable_flow_control = configuration.disable_flow_control

    def _get_captured_request(self):
        """Returns the last request that was passed into ``_send_events`` by the CopyingManager, or None if there
        wasn't any.

        This will also reset the captured request to None so the returned request won't be returned twice.

        @return: The last request
        @rtype: AddEventsRequest
        """
        self._test_state_cv.acquire()
        try:
            result = self._captured_request
            self._captured_request = None
            return result
        finally:
            self._test_state_cv.release()

    def _set_response(self, status_message):
        """Sets the status_message to return as the response for the next AddEventsRequest.

        @param status_message: The status message
        @type status_message: six.text_type
        """
        self._test_state_cv.acquire()
        self._pending_response = status_message
        self._test_state_cv.release()

    def perform_scan(self):
        """Tells the CopyingManagerWorker thread to go through the process loop until far enough where it has performed
        the scan of the file system looking for new bytes in the log file.

        At this point, the CopyingManagerWorker should have a request ready to be sent.
        """
        # We guarantee it has scanned by making sure it has gone from sleeping to sending.
        self.run_and_stop_at(
            TestableCopyingManagerFlowController.SENDING,
            required_transition_state=TestableCopyingManagerFlowController.SLEEPING,
        )

    def perform_pipeline_scan(self):
        """Tells the CopyingManagerWorker thread to advance far enough where it has performed the file system scan
        for the pipelined AddEventsRequest, if the manager is configured to send one..

        This is only valid to call immediately after a ``perform_scan``
        """
        # We guarantee it has done the pipeline scan by making sure it has gone through responding to sending.
        self.run_and_stop_at(
            TestableCopyingManagerFlowController.RESPONDING,
            required_transition_state=TestableCopyingManagerFlowController.SENDING,
        )

    def wait_for_full_iteration(self):
        self.run_and_stop_at(TestableCopyingManagerThreadedWorker.SLEEPING,)

        self.run_and_stop_at(
            TestableCopyingManagerThreadedWorker.SENDING,
            required_transition_state=TestableCopyingManagerThreadedWorker.SLEEPING,
        )

        self.run_and_stop_at(
            TestableCopyingManagerThreadedWorker.SLEEPING,
            required_transition_state=TestableCopyingManagerThreadedWorker.SENDING,
        )

    def _block_if_should_stop_at(self, current_point):
        """Invoked by the CopyManager thread to report it has transitioned to the specified state and will block if
        `run_and_stop_at` has been invoked with `current_point` as the stopping point.

        @param current_point: The point reached by the CopyingManager thread, only valid values are
            `SLEEPING`, `SENDING`, and `RESPONDING`.
        @type current_point: six.text_type
        """

        # Do nothing if flow control has been disabled.
        if self._disable_flow_control:
            return

        # If we are passing through the required_transition state, consume it to signal we have accomplished
        # the transition.
        if current_point == self._test_required_transition:
            self._test_required_transition = None

        # Block if it has been requested that we block here.  Note, __test_stop_state can only be:
        # 'all'  -- indicating it should stop at the first state it sees.
        # None -- indicating the test is shutting down and the CopyingManger thread should just run until it finishes
        # One of `SLEEPING`, `SENDING`, and `RESPONDING` -- indicating where we should next block the CopyingManager.
        start_time = time.time()
        while self._test_stop_state == "all" or current_point == self._test_stop_state:
            self._test_is_stopped = True
            if self._test_required_transition is not None:
                raise AssertionError(
                    "Stopped at %s state but did not transition through %s"
                    % (current_point, self._test_required_transition)
                )
            # This notifies any threads waiting in the `run_and_stop_at` method.  They would be blocking waiting for
            # the CopyingManager thread to stop at this point.
            self._test_state_cv.notifyAll()
            # We need to wait until some other state is set as the stop state.  The `notifyAll` in `run_and_stop_at`
            # method will wake us up.
            self._test_state_cv_wait_with_timeout(start_time)

        self._test_is_stopped = False

    def run_and_stop_at(self, stopping_at, required_transition_state=None):
        """Invoked by the testing thread to indicate the CopyingManager thread should run and keep running until
        it enters the specified state.  If `required_transition_state` is specified, then the CopyingManager thread
        must transition through the specified state before it stops, otherwise an AssertionError will be raised.

        Note, if the CopyingManager thread is already stopping in the `stopping_at` thread, then this call will
        immediately return.  It does not wait for the next occurrence of that state.

        @param stopping_at: The state to stop at.  Only valid values are `SLEEPING`, `SENDING`, `RESPONDING`
        @param required_transition_state: If not None, requires that the CopyingManager transitions through the
            specified state before it gets to `stopping_at`.  Otherwise an AssertionError will be thrown.
              Only valid values are `SLEEPING`, `SENDING`, `RESPONDING`

        @type stopping_at: six.text_type
        @type required_transition_state: six.text_type or None
        """

        # Do nothing if flow control has been disabled.
        if self._disable_flow_control:
            return

        self._test_state_cv.acquire()
        try:
            # Just to avoid mistakes in testing, make sure we successfully consumed any require transitions before
            # we tell it to stop anywhere else.
            if self._test_required_transition is not None:
                raise AssertionError(
                    "Setting new stop state %s with pending required transition %s"
                    % (stopping_at, self._test_required_transition)
                )
            # If we are already in the required_transition_state, consume it.
            if (
                self._test_is_stopped
                and self._test_stop_state == required_transition_state
            ):
                self._test_required_transition = None
            else:
                self._test_required_transition = required_transition_state

            if self._test_is_stopped and self._test_stop_state == stopping_at:
                return

            self._test_stop_state = stopping_at
            self._test_is_stopped = False
            # This will wake up threads in `_block_if_should_stop_at` which are waiting for a new stopping point.
            self._test_state_cv.notifyAll()

            start_time = time.time()
            # Wait until we get to this point.
            while not self._test_is_stopped:
                # This will be woken up by the notify in `_block_if_should_stop_at` method.
                self._test_state_cv_wait_with_timeout(start_time)
        finally:
            self._test_state_cv.release()

    def _test_state_cv_wait_with_timeout(self, start_time):
        """Waits on the `_test_state_cv` condition variable, but will also throw an AssertionError if the wait
        time exceeded the `start_time` plus `WAIT_TIMEOUT`.

        @param start_time:  The start time when we first began waiting on this condition, in seconds past epoch.
        @type start_time: Number
        """
        deadline = start_time + TestableCopyingManagerThreadedWorker.WAIT_TIMEOUT
        self._test_state_cv.wait(timeout=(deadline - time.time()) + 0.5)
        if time.time() > deadline:
            raise AssertionError(
                "Deadline exceeded while waiting on condition variable"
            )


class TestableCopyingManagerThreadedWorker(
    CopyingManagerThreadedWorker, TestableCopyingManagerFlowController
):
    """An instrumented version of the CopyingManagerWorker which allows intercepting of requests sent, control when
    the worker processes new logs, etc.

    This allows for end-to-end testing of the core of the CopyingManagerWorker.

    Doing this right is a bit complicated because the CopyingManagerWorker runs in its own thread.

    Many members of this class are common with the TestableCopyingManager class
    and moved to the base class - TestableCopyingManagerFlowController
    """

    __test__ = False

    def __init__(self, configuration, api_key_config_entry, worker_id):
        # Approach:  We will override key methods of CopyingManagerWorker, blocking them from returning until we tell
        # to proceed.  This allows us to then do things like write new log lines while the CopyingManagerWorker is
        # blocked.   Coordinating the communication between the two threads is done using one condition variable.
        # We changed the CopyingManagerWorker to block in three places: while it is sleeping before it starts a new loop,
        # when it invokes `_send_events` to send a new request, and when it blocks to receive the response.
        # These three states are referred to as 'sleeping', 'sending', 'responding'.
        #
        # The CopyingManagerWorker will have state to record where it should next block (i.e., if it should block at
        # 'sleeping' when it attempts to sleep).
        #
        # We can manipulate this state, notifying changes on the conditional variable
        # by using following methods: 'wait_for_rpc', 'perform_scan', 'perform_pipeline_scan'
        # The CopyingManagerWorker will block in this state (and indicate it is blocked) until the
        # we set a new state to block at.

        CopyingManagerThreadedWorker.__init__(
            self, configuration, api_key_config_entry, worker_id
        )
        TestableCopyingManagerFlowController.__init__(self, configuration)
        self.__config = configuration

        # the copying manager deletes worker checkpoint files when it stops.
        # This variable preserves the content of thos files for testing.
        self._saved_checkpoints = None
        self.saved_active_checkpoints = None

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Blocks the CopyingManagerWorker thread until the controller tells it to proceed.
        """

        if self._disable_flow_control:
            # flow control is disabled. Just return.
            time.sleep(0.01)
            return

        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(TestableCopyingManagerThreadedWorker.SLEEPING)
        finally:
            self._test_state_cv.release()

    def _create_add_events_request(self, session_info=None, max_size=None):
        # Need to override this to return an AddEventsRequest even though we don't have a real scalyr client instance.
        if session_info is None:
            body = dict(server_attributes=session_info, token="fake")
        else:
            body = dict(token="fake")

        return AddEventsRequest(body, max_size=max_size)

    def _send_events(self, add_events_task):
        """Captures ``add_events_task`` and emulates sending an AddEventsTask.

        This method will not return until the controller tells it to advance to the next state.
        """
        # First, block even returning from this method until the controller advances us.

        if self._disable_flow_control:
            # flow control is disabled, just return a dummy response callback.
            def get_response():
                """"""
                return "success", 0, "fake"

            return get_response

        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(TestableCopyingManagerThreadedWorker.SENDING)
            self._captured_request = add_events_task.add_events_request
        finally:
            self._test_state_cv.release()

        # Create a method that we can return that will (when invoked) return the response
        def emit_response():
            # Block on return the response until the state is advanced.
            self._test_state_cv.acquire()
            try:
                self._block_if_should_stop_at(
                    TestableCopyingManagerThreadedWorker.RESPONDING
                )

                # Use the pending response if there is one.  Otherwise, we just say "success" which means all add event
                # requests will just be processed.
                result = self._pending_response
                self._pending_response = None
            finally:
                self._test_state_cv.release()

            if result is not None:
                return result, 0, "fake"
            else:
                return "success", 0, "fake"

        return emit_response

    def start_worker(self, stop_at=TestableCopyingManagerFlowController.SLEEPING):
        """
        Overrides base class method, to initialize "scalyr_client" by default.
        """
        super(TestableCopyingManagerThreadedWorker, self).start_worker()

        if not self._disable_flow_control and stop_at:
            self.run_and_stop_at(stop_at)

    def stop_worker(self, wait_on_join=True, join_timeout=5):
        """Stops the worker's thread.

        @param wait_on_join:  Whether or not to wait on thread to finish.
        @param join_timeout:  The number of seconds to wait on the join.
        @type wait_on_join: bool
        @type join_timeout: float
        @return:
        @rtype:
        """

        if not self._disable_flow_control:
            # We need to do some extra work here in case the CopyingManagerWorker thread is currently in a blocked state.
            # We need to tell it to keep running.
            self._test_state_cv.acquire()
            self._test_stop_state = None
            self._test_state_cv.notifyAll()
            self._test_state_cv.release()

        CopyingManagerThreadedWorker.stop_worker(
            self, wait_on_join=wait_on_join, join_timeout=join_timeout
        )

    def _init_scalyr_client(self, quiet=False):
        """
        Override and do nothing in order to avoid making a real connection with the Scalyr.
        :return:
        """
        pass

    def wait_for_rpc(self, with_callback=True):
        """Tells the CopyingManagerWorker thread to advance to the point where it has emulated sending an RPC.

        @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManagerWorker and a function that
            when invoked will return the passed in status message as the response to the AddEventsRequest.
        @rtype: (AddEventsRequest, func)
        """
        self.run_and_stop_at(TestableCopyingManagerThreadedWorker.RESPONDING)
        request = self._get_captured_request()

        if with_callback:
            return request, self.send_current_response

        return request

    def send_current_response(self, status_message):
        """
        This is a function for the response callback. We need this as a separate function to be able to expose it
        through a proxy if multiprocess workers are used.
        :param status_message: Response message for the request.
        """
        self._set_response(status_message)
        self.run_and_stop_at(TestableCopyingManagerThreadedWorker.SLEEPING)

    def close_at_eof(self, filepath):
        """Tells the CopyingManagerWorker to mark the LogFileProcessor copying the specified path to close itself
        once all bytes have been copied up to Scalyr.  This can be used to remove LogProcessors for
        testing purposes.

        :param filepath: The path of the processor.
        :type filepath: six.text_type
        """
        # noinspection PyProtectedMember
        log_processor = next(
            p for p in self.get_log_processors() if p.get_log_path() == filepath
        )
        log_processor.close_at_eof()

    def _write_full_checkpoint_state(self, current_time):
        """
        Override this method to preserve the data of the checkpoint files in case
        if this function has been invoked before stop. (Copying manager removes
        worker files when stops)
        :param current_time:
        :return:
        """
        super(TestableCopyingManagerThreadedWorker, self)._write_full_checkpoint_state(
            current_time
        )
        self._saved_checkpoints, self.saved_active_checkpoints = self.get_checkpoints()

    # region Utility funtions
    def get_checkpoints_path(self):
        result = pathlib.Path(
            self.__config.agent_data_path, "checkpoints-%s.json" % self._id
        )
        return result

    def get_active_checkpoints_path(self):
        result = pathlib.Path(
            self.__config.agent_data_path, "active-checkpoints-%s.json" % self._id
        )
        return result

    def get_checkpoints(self):
        """
        Get checkpoint states of the worker.
        :return:
        """
        if self.get_checkpoints_path().exists():
            checkpoints = json.loads(self.get_checkpoints_path().read_text())
        else:
            checkpoints = self._saved_checkpoints
        if self.get_active_checkpoints_path().exists():
            active_checkpoints = json.loads(
                self.get_active_checkpoints_path().read_text()
            )
        else:
            active_checkpoints = self.saved_active_checkpoints

        return checkpoints, active_checkpoints

    def write_checkpoints(self, path, data):
        # type: (pathlib.Path, Dict) -> None
        path.write_text(six.ensure_text(json.dumps(data)))

    def change_last_attempt_time(self, value):
        self._CopyingManagerThreadedWorker__last_attempt_time = value

    @property
    def last_attempt_time(self):
        return self._CopyingManagerThreadedWorker__last_attempt_time

    def get_pid(self):
        return os.getpid()

    # endregion


class TestableApiKeyWorkerPool(ApiKeyWorkerPool):
    def __init__(self, config, api_key_config):
        # type: (TestingConfiguration, Dict) -> None
        self._skip_agent_log_change = config.skip_agent_log_change
        super(TestableApiKeyWorkerPool, self).__init__(config, api_key_config)

    def _change_worker_process_agent_log_path(self, path):
        """
        If there ia an appropriate configuration value,
        we do not say change agent log path for workers,
        because some of the test cases do not create agent log files at all.
        """
        if not self._skip_agent_log_change:
            super(TestableApiKeyWorkerPool, self)._change_worker_process_agent_log_path(
                path
            )

    def _stop_shared_object_managers(self):
        """
        We may need to interact with workers even after manager is stopped,
         so do not stop the shared object managers.
        """
        pass

    def stop_shared_object_managers(self):
        """
         Because the '_stop_shared_object_managers' is stubbed,
        we need to have another method to stop the shaded object managers when it is really time.
        """
        return super(TestableApiKeyWorkerPool, self)._stop_shared_object_managers()


class TestableLogMatcher(LogMatcher):
    """
        The subclass of the LogMatcher class with helper functions.
        This is used in the TestableCopying manager
        instead of the regular LogMatcher.
    """

    @property
    def log_processors(self):
        return self._processors


class TestableCopyingManager(CopyingManager, TestableCopyingManagerFlowController):
    """
    Since the real copying happens in the workers of the CopyingManager, this abstraction
    is used to synchronize its worker instances.
    The main goal of this - is to provide the same interface as TestalbeCopyingManagerWorker provides
    and to control workers seamlessly through the copying manager.
    NOTE: Many members do not differ from  some members of the TestableCopyingManagerWorker,
    so they were moved into common base class - TestableCopyingManagerFlowController. Please see also there.
    """

    def __init__(self, configuration, monitors):
        CopyingManager.__init__(self, configuration, monitors)
        TestableCopyingManagerFlowController.__init__(self, configuration)

        # do this just to tell static analyzer that this is a testable instances.
        self._log_matchers = self._log_matchers  # type: List[TestableLogMatcher]

    def _create_worker_pools(self):
        # We are going to control the flow of our
        # workers by using 'TestableCopyingManagerWorker' subclass of the 'CopyingManagerWorker'
        # that's why we need change original worker class by testable class.
        # We also do the same thing with 'ApiKeyWorkerPool' and the shared object manager class
        from scalyr_agent.copying_manager import copying_manager

        # save original class of the CopyingManager from 'copying_manager' module
        original_worker = copying_manager.CopyingManagerThreadedWorker
        original_worker_pool = copying_manager.ApiKeyWorkerPool
        original_shared_object_manager_class = copying_manager.SharedObjectManager

        # replace original class by testable.
        copying_manager.SharedObjectManager = TestableSharedObjectManager
        copying_manager.CopyingManagerThreadedWorker = (
            TestableCopyingManagerThreadedWorker
        )
        copying_manager.ApiKeyWorkerPool = TestableApiKeyWorkerPool

        try:
            super(TestableCopyingManager, self)._create_worker_pools()
        finally:
            # return back original worker class.
            copying_manager.CopyingManagerThreadedWorker = original_worker
            copying_manager.SharedObjectManager = original_shared_object_manager_class
            copying_manager.ApiKeyWorkerPool = original_worker_pool

    def _create_log_matchers(self, configuration, monitors):
        # override this to mock regular log matchers with testable ones.
        with mock.patch.object(copying_manager, "LogMatcher", TestableLogMatcher):
            return super(TestableCopyingManager, self)._create_log_matchers(
                configuration, monitors
            )

    def add_log_config(self, monitor_name, log_config, force_add=False):
        # override this to mock regular log matchers with testable ones.
        with mock.patch.object(copying_manager, "LogMatcher", TestableLogMatcher):
            return super(TestableCopyingManager, self).add_log_config(
                monitor_name, log_config, force_add=force_add
            )

    def start_manager(
        self, logs_initial_positions=None,
    ):
        """
        Overrides base class method, to initialize "scalyr_client" by default.
        """

        super(TestableCopyingManager, self).start_manager(
            logs_initial_positions=logs_initial_positions
        )

    def _sleep_but_awaken_if_stopped(self, seconds):
        """
        This method is overridden for in order to synchronize with
        its workers. After each loop, the copying manager enters this method and manipulates its workers.

        :param seconds:
        :return:
        """

        # if flow control disabled, just do nothing.
        if self._disable_flow_control:
            time.sleep(0.01)
            return

        self._test_state_cv.acquire()
        try:

            # this block is used to synchronize with workers before the do their "send_event".
            self._block_if_should_stop_at(TestableCopyingManagerFlowController.SENDING)
            responder_callbacks = list()
            requests = list()
            # get requests from every worker
            # for api_key_pool in self._api_keys_worker_pools.values():
            for worker in self.workers:
                request, responder_callback = worker.wait_for_rpc()

                # save respond callbacks to be able to set responses for requests that were made by workers.
                responder_callbacks.append(responder_callback)
                # save requests so the can be returned by 'self.wait_for_rpc' later.
                requests.append(request)

            self._captured_request = requests

        finally:
            self._test_state_cv.release()

        self._test_state_cv.acquire()
        try:

            # this block is used to synchronize with workers before they get response for their requests.
            self._block_if_should_stop_at(
                TestableCopyingManagerFlowController.RESPONDING
            )

            if self._pending_response is None:
                result = "success"
            else:
                result = self._pending_response

            for rc in responder_callbacks:
                rc(result)
        finally:
            self._test_state_cv.release()

        self._test_state_cv.acquire()
        try:
            # this block is used to synchronize with workers before they go to sleep before the next loop.
            self._block_if_should_stop_at(TestableCopyingManagerFlowController.SLEEPING)
        finally:
            self._test_state_cv.release()

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops the manager's thread.

        @param wait_on_join:  Whether or not to wait on thread to finish.
        @param join_timeout:  The number of seconds to wait on the join.
        @type wait_on_join: bool
        @type join_timeout: float
        @return:
        @rtype:
        """

        if not self._disable_flow_control:
            # We need to do some extra work here in case the CopyingManager thread is currently in a blocked state.
            # We need to tell it to keep running.
            self._test_state_cv.acquire()
            self._test_stop_state = None
            self._test_state_cv.notifyAll()
            self._test_state_cv.release()

        CopyingManager.stop_manager(
            self, wait_on_join=wait_on_join, join_timeout=join_timeout
        )

    def cleanup(self):
        """
        Stopping the shared object managers from api worker pools.
        """
        for worker_pool in self.api_keys_worker_pools.values():
            worker_pool.stop_shared_object_managers()

    def perform_scan(self):
        """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
        the scan of the file system looking for new bytes in the log file.

        At this point, the CopyingManager should have a request ready to be sent.
        """

        # We guarantee it has scanned by making sure it has gone from sleeping to sending.
        super(TestableCopyingManager, self).perform_scan()

        for worker in self.workers:
            worker.perform_scan()

    def wait_for_rpc(self):
        # type: () -> Tuple[List[AddEventsRequest], Callable]
        """Tells the CopyingManager thread to advance to the point where its workers have emulated sending an RPC.

        @return:  A tuple containing the list of AddEventsRequest's that were sent by each worker and a function that
            when invoked will set the passed in status message as the response to the AddEventsRequest for each worker.
        """

        self.run_and_stop_at(TestableCopyingManager.RESPONDING)
        requests = self._get_captured_request()

        def send_response(status_message):
            self._set_response(status_message)
            self.run_and_stop_at(TestableCopyingManager.SLEEPING)

        return requests, send_response

    # region Utility functions
    @property
    def workers(self):
        # type: () -> List[TestableCopyingManagerThreadedWorker]
        """
        Return all workers from all worker pools as a single list.
        :return:
        """
        result = []
        for api_key_pool in self.api_keys_worker_pools.values():
            result.extend(api_key_pool.workers)
        return result

    @property
    def consolidated_checkpoints_path(self):
        # type: () -> pathlib.Path
        return pathlib.Path(self.config.agent_data_path, "checkpoints.json")

    @property
    def consolidated_checkpoints(self):
        # type: () -> Dict
        return json.loads(self.consolidated_checkpoints_path.read_text())

    def write_consolidated_checkpoints(self, checkpoints):
        # type: (Dict) -> None
        self.consolidated_checkpoints_path.write_text(
            six.text_type(json.dumps(checkpoints))
        )

    @property
    def matchers_log_processor_count(self):
        return sum(len(m.log_processors) for m in self.log_matchers)

    @property
    def workers_log_processors_count(self):
        return sum(len(w.get_log_processors()) for w in self.workers)

    # endregion


# create proxy class for the testable worker. The testable worker has its own methods that also have to be exposed
# by proxies.
_TestableCopyingManagerWorkerProxy = multiprocessing.managers.MakeProxyType(
    six.ensure_str("CopyingManagerWorkerProxy"),
    WORKER_PROXY_EXPOSED_METHODS
    + [
        six.ensure_str("run_and_stop_at"),
        six.ensure_str("wait_for_rpc"),
        six.ensure_str("send_current_response"),
        six.ensure_str("perform_scan"),
        six.ensure_str("wait_for_full_iteration"),
        six.ensure_str("perform_pipeline_scan"),
        six.ensure_str("close_at_eof"),
        six.ensure_str("generate_status"),
        six.ensure_str("change_last_attempt_time"),
        six.ensure_str("is_alive"),
        six.ensure_str("get_pid"),
        six.ensure_str("get_active_checkpoints_path"),
        six.ensure_str("get_checkpoints_path"),
        six.ensure_str("_init_scalyr_client"),
        six.ensure_str("change_agent_log"),
    ],
)


class TestableCopyingManagerWorkerProxy(_TestableCopyingManagerWorkerProxy):
    def wait_for_rpc(self, *args, **kwargs):
        """
        Override this method for proxy to be able to return the callable objects.
        The main problem here - is that the it is problematically to return callable objects.
        Insted of that, we use previously exposed member function 'send_current_response' as a callback.

        All parameters are passed directly to the "wait_for rpc" method of the proxy.
        :return:
        """
        kwargs["with_callback"] = False
        request = self._callmethod("wait_for_rpc", args=args, kwds=kwargs)

        def send_response(status_message):
            self._callmethod("send_current_response", args=(status_message,))

        return request, send_response


TestableSharedObjectManager = create_shared_object_manager(
    TestableCopyingManagerThreadedWorker, TestableCopyingManagerWorkerProxy
)
