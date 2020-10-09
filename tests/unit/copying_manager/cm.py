from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

import time
import threading

from scalyr_agent.new_copying_manager.worker import CopyingManagerWorker
from scalyr_agent.new_copying_manager.worker import AddEventsTask

from scalyr_agent.new_copying_manager.copying_manager import CopyingManager


from scalyr_agent.scalyr_client import AddEventsRequest


class BaseTestableCopyingManager:
    """An instrumented version of the CopyingManager which allows intercepting of requests sent, control when
    the manager processes new logs, etc.

    This allows for end-to-end testing of the core of the CopyingManager.

    Doing this right is a bit complicated because the CopyingManager runs in its own thread.

    To actually control the copying manager, use the TestController object returned by ``controller``.
    """

    __test__ = False

    # The different points at which the CopyingManager can be stopped.  See below.
    SLEEPING = "SLEEPING"
    SENDING = "SENDING"
    RESPONDING = "RESPONDING"

    # To prevent tests from hanging indefinitely, wait a maximum amount of time before giving up on some test condition.
    WAIT_TIMEOUT = 50000.0

    def __init__(self):
        # CopyingManager.__init__(self, configuration, monitors, mode=mode)
        # Approach:  We will override key methods of CopyingManager, blocking them from returning until the controller
        # tells it to proceed.  This allows us to then do things like write new log lines while the CopyingManager is
        # blocked.   Coordinating the communication between the two threads is done using one condition variable.
        # We changed the CopyingManager to block in three places: while it is sleeping before it starts a new loop,
        # when it invokes `_send_events` to send a new request, and when it blocks to receive the response.
        # These three states are referred to as 'sleeping', 'sending', 'responding'.
        #
        # The CopyingManager will have state to record where it should next block (i.e., if it should block at
        # 'sleeping' when it attempts to sleep).  The test controller will manipulate this state, notifying changes on
        # the condition variable. The CopyingManager will block in this state (and indicate it is blocked) until the
        # test controller sets a new state to block at.
        #
        # This cv protects all of the variables written by the CopyingManager thread.
        self._test_state_cv = threading.Condition()
        # Which state the CopyingManager should block in -- "sleeping", "sending", "responding"
        # We initialize it to a special value "all" so that it stops as soon the CopyingManager starts up.
        self._test_stop_state = "all"
        # If not none, a state the test must pass through before it tries to stop at `__test_stop_state`.
        # If this transition is not observed by the time it does get to the stop state, an assertion is thrown.
        self._test_required_transition = None
        # Whether or not the CopyingManager is stopped at __test_stop_state.
        self._test_is_stopped = False

    def captured_request(self):
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

    def set_response(self, status_message):
        """Sets the status_message to return as the response for the next AddEventsRequest.

        @param status_message: The status message
        @type status_message: six.text_type
        """
        self._test_state_cv.acquire()
        self._pending_response = status_message
        self._test_state_cv.release()

    def _block_if_should_stop_at(self, current_point):
        """Invoked by the CopyManager thread to report it has transitioned to the specified state and will block if
        `run_and_stop_at` has been invoked with `current_point` as the stopping point.

        @param current_point: The point reached by the CopyingManager thread, only valid values are
            `SLEEPING`, `SENDING`, and `RESPONDING`.
        @type current_point: six.text_type
        """
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
        print(("State %s" % self._test_stop_state))
        deadline = start_time + TestableCopyingManagerWorker.WAIT_TIMEOUT
        self._test_state_cv.wait(timeout=(deadline - time.time()) + 0.5)
        if time.time() > deadline:
            raise AssertionError(
                "Deadline exceeded while waiting on condition variable"
            )

    # class TestController(object):
    #     """Used to control the TestableCopyingManager.
    #
    #     Its main role is to tell the manager thread when to unblock and how far to run.
    #     """
    #
    #     def __init__(self, copying_manager):
    #         self.__copying_manager = copying_manager
    #
    #     def perform_scan(self):
    #         """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
    #         the scan of the file system looking for new bytes in the log file.
    #
    #         At this point, the CopyingManager should have a request ready to be sent.
    #         """
    #         # We guarantee it has scanned by making sure it has gone from sleeping to sending.
    #         self.__copying_manager.run_and_stop_at(
    #             TestableCopyingManager.SENDING,
    #             required_transition_state=TestableCopyingManager.SLEEPING,
    #         )
    #
    #     def perform_pipeline_scan(self):
    #         """Tells the CopyingManager thread to advance far enough where it has performed the file system scan
    #         for the pipelined AddEventsRequest, if the manager is configured to send one..
    #
    #         This is only valid to call immediately after a ``perform_scan``
    #         """
    #         # We guarantee it has done the pipeline scan by making sure it has gone through responding to sending.
    #         self.__copying_manager.run_and_stop_at(
    #             TestableCopyingManager.RESPONDING,
    #             required_transition_state=TestableCopyingManager.SENDING,
    #         )
    #
    #     def wait_for_rpc(self):
    #         """Tells the CopyingManager thread to advance to the point where it has emulated sending an RPC.
    #
    #         @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManager and a function that
    #             when invoked will return the passed in status message as the response to the AddEventsRequest.
    #         @rtype: (AddEventsRequest, func)
    #         """
    #         self.__copying_manager.run_and_stop_at(TestableCopyingManager.RESPONDING)
    #         request = self.__copying_manager.captured_request()
    #
    #         def send_response(status_message):
    #             self.__copying_manager.set_response(status_message)
    #             self.__copying_manager.run_and_stop_at(TestableCopyingManager.SLEEPING)
    #
    #         return request, send_response
    #
    #     def close_at_eof(self, filepath):
    #         """Tells the CopyingManager to mark the LogProcessor copying the specified path to close itself
    #         once all bytes have been copied up to Scalyr.  This can be used to remove LogProcessors for
    #         testing purposes.
    #
    #         :param filepath: The path of the processor.
    #         :type filepath: six.text_type
    #         """
    #         # noinspection PyProtectedMember
    #         self.__copying_manager._CopyingManager__log_paths_being_processed[
    #             filepath
    #         ].close_at_eof()


class TestableCopyingManagerWorker(CopyingManagerWorker, BaseTestableCopyingManager):
    """An instrumented version of the CopyingManager which allows intercepting of requests sent, control when
    the manager processes new logs, etc.

    This allows for end-to-end testing of the core of the CopyingManager.

    Doing this right is a bit complicated because the CopyingManager runs in its own thread.

    To actually control the copying manager, use the TestController object returned by ``controller``.
    """

    __test__ = False

    # The different points at which the CopyingManager can be stopped.  See below.
    SLEEPING = "SLEEPING"
    SENDING = "SENDING"
    RESPONDING = "RESPONDING"

    # To prevent tests from hanging indefinitely, wait a maximum amount of time before giving up on some test condition.
    WAIT_TIMEOUT = 50000.0

    def __init__(self, configuration):
        CopyingManagerWorker.__init__(self, configuration)
        BaseTestableCopyingManager.__init__(self)

        # Written by CopyingManager.  The last AddEventsRequest request passed into ``_send_events``.
        self.__captured_request = None
        # Protected by _test_state_cv.  The status message to return for the next call to ``_send_events``.
        self.__pending_response = None

        self.__iterations_count = 0

        self.controller = TestableCopyingManagerWorker.TestController(self)

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Blocks the CopyingManager thread until the controller tells it to proceed.
        """
        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(TestableCopyingManagerWorker.SLEEPING)
            self.__iterations_count += 1
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
        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(TestableCopyingManagerWorker.SENDING)
            self.__captured_request = add_events_task.add_events_request
        finally:
            self._test_state_cv.release()

        # Create a method that we can return that will (when invoked) return the response
        def emit_response():
            # Block on return the response until the state is advanced.
            self._test_state_cv.acquire()
            try:
                self._block_if_should_stop_at(TestableCopyingManagerWorker.RESPONDING)

                # Use the pending response if there is one.  Otherwise, we just say "success" which means all add event
                # requests will just be processed.
                result = self.__pending_response
                self.__pending_response = None
            finally:
                self._test_state_cv.release()

            if result is not None:
                return result, 0, "fake"
            else:
                return "success", 0, "fake"

        return emit_response

    def captured_request(self):
        """Returns the last request that was passed into ``_send_events`` by the CopyingManager, or None if there
        wasn't any.

        This will also reset the captured request to None so the returned request won't be returned twice.

        @return: The last request
        @rtype: AddEventsRequest
        """
        self._test_state_cv.acquire()
        try:
            result = self.__captured_request
            self.__captured_request = None
            return result
        finally:
            self._test_state_cv.release()

    def set_response(self, status_message):
        """Sets the status_message to return as the response for the next AddEventsRequest.

        @param status_message: The status message
        @type status_message: six.text_type
        """
        self._test_state_cv.acquire()
        self.__pending_response = status_message
        self._test_state_cv.release()

    # def __block_if_should_stop_at(self, current_point):
    #     """Invoked by the CopyManager thread to report it has transitioned to the specified state and will block if
    #     `run_and_stop_at` has been invoked with `current_point` as the stopping point.
    #
    #     @param current_point: The point reached by the CopyingManager thread, only valid values are
    #         `SLEEPING`, `SENDING`, and `RESPONDING`.
    #     @type current_point: six.text_type
    #     """
    #     # If we are passing through the required_transition state, consume it to signal we have accomplished
    #     # the transition.
    #     if current_point == self.__test_required_transition:
    #         self.__test_required_transition = None
    #
    #     # Block if it has been requested that we block here.  Note, __test_stop_state can only be:
    #     # 'all'  -- indicating it should stop at the first state it sees.
    #     # None -- indicating the test is shutting down and the CopyingManger thread should just run until it finishes
    #     # One of `SLEEPING`, `SENDING`, and `RESPONDING` -- indicating where we should next block the CopyingManager.
    #     start_time = time.time()
    #     while (
    #         self.__test_stop_state == "all" or current_point == self.__test_stop_state
    #     ):
    #         self.__test_is_stopped = True
    #         if self.__test_required_transition is not None:
    #             raise AssertionError(
    #                 "Stopped at %s state but did not transition through %s"
    #                 % (current_point, self.__test_required_transition)
    #             )
    #         # This notifies any threads waiting in the `run_and_stop_at` method.  They would be blocking waiting for
    #         # the CopyingManager thread to stop at this point.
    #         self.__test_state_cv.notifyAll()
    #         # We need to wait until some other state is set as the stop state.  The `notifyAll` in `run_and_stop_at`
    #         # method will wake us up.
    #         self.__test_state_cv_wait_with_timeout(start_time)
    #
    #     self.__test_is_stopped = False

    # def run_and_stop_at(self, stopping_at, required_transition_state=None):
    #     """Invoked by the testing thread to indicate the CopyingManager thread should run and keep running until
    #     it enters the specified state.  If `required_transition_state` is specified, then the CopyingManager thread
    #     must transition through the specified state before it stops, otherwise an AssertionError will be raised.
    #
    #     Note, if the CopyingManager thread is already stopping in the `stopping_at` thread, then this call will
    #     immediately return.  It does not wait for the next occurrence of that state.
    #
    #     @param stopping_at: The state to stop at.  Only valid values are `SLEEPING`, `SENDING`, `RESPONDING`
    #     @param required_transition_state: If not None, requires that the CopyingManager transitions through the
    #         specified state before it gets to `stopping_at`.  Otherwise an AssertionError will be thrown.
    #           Only valid values are `SLEEPING`, `SENDING`, `RESPONDING`
    #
    #     @type stopping_at: six.text_type
    #     @type required_transition_state: six.text_type or None
    #     """
    #     self.__test_state_cv.acquire()
    #     try:
    #         # Just to avoid mistakes in testing, make sure we successfully consumed any require transitions before
    #         # we tell it to stop anywhere else.
    #         if self.__test_required_transition is not None:
    #             raise AssertionError(
    #                 "Setting new stop state %s with pending required transition %s"
    #                 % (stopping_at, self.__test_required_transition)
    #             )
    #         # If we are already in the required_transition_state, consume it.
    #         if (
    #             self.__test_is_stopped
    #             and self.__test_stop_state == required_transition_state
    #         ):
    #             self.__test_required_transition = None
    #         else:
    #             self.__test_required_transition = required_transition_state
    #
    #         if self.__test_is_stopped and self.__test_stop_state == stopping_at:
    #             return
    #
    #         self.__test_stop_state = stopping_at
    #         self.__test_is_stopped = False
    #         # This will wake up threads in `__block_if_should_stop_at` which are waiting for a new stopping point.
    #         self.__test_state_cv.notifyAll()
    #
    #         start_time = time.time()
    #         # Wait until we get to this point.
    #         while not self.__test_is_stopped:
    #             # This will be woken up by the notify in `__block_if_should_stop_at` method.
    #             self.__test_state_cv_wait_with_timeout(start_time)
    #     finally:
    #         self.__test_state_cv.release()

    # def __test_state_cv_wait_with_timeout(self, start_time):
    #     """Waits on the `__test_state_cv` condition variable, but will also throw an AssertionError if the wait
    #     time exceeded the `start_time` plus `WAIT_TIMEOUT`.
    #
    #     @param start_time:  The start time when we first began waiting on this condition, in seconds past epoch.
    #     @type start_time: Number
    #     """
    #     deadline = start_time + TestableCopyingManager.WAIT_TIMEOUT
    #     self.__test_state_cv.wait(timeout=(deadline - time.time()) + 0.5)
    #     if time.time() > deadline:
    #         raise AssertionError(
    #             "Deadline exceeded while waiting on condition variable"
    #         )
    #
    # def stop_manager(self, wait_on_join=True, join_timeout=5):
    #     """Stops the manager's thread.
    #
    #     @param wait_on_join:  Whether or not to wait on thread to finish.
    #     @param join_timeout:  The number of seconds to wait on the join.
    #     @type wait_on_join: bool
    #     @type join_timeout: float
    #     @return:
    #     @rtype:
    #     """
    #     # We need to do some extra work here in case the CopyingManager thread is currently in a blocked state.
    #     # We need to tell it to keep running.
    #     self.__test_state_cv.acquire()
    #     self.__test_stop_state = None
    #     self.__test_state_cv.notifyAll()
    #     self.__test_state_cv.release()
    #
    #     CopyingManager.stop_manager(
    #         self, wait_on_join=wait_on_join, join_timeout=join_timeout
    #     )
    #
    def start_worker(self, scalyr_client=None, stop_at=SLEEPING):
        """
        Overrides base class method, to initialize "scalyr_client" by default.
        """
        if scalyr_client is None:
            scalyr_client = dict(fake_client=True)
        super(TestableCopyingManagerWorker, self).start_worker(scalyr_client)

        if stop_at:
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
        # We need to do some extra work here in case the CopyingManagerWorker thread is currently in a blocked state.
        # We need to tell it to keep running.
        self._test_state_cv.acquire()
        self._test_stop_state = None
        self._test_state_cv.notifyAll()
        self._test_state_cv.release()

        CopyingManagerWorker.stop_worker(
            self, wait_on_join=wait_on_join, join_timeout=join_timeout
        )

    @property
    def log_processors(self):

        with self._CopyingManagerWorker__lock:
            return self._CopyingManagerWorker__log_processors.copy()

    class TestController(object):
        """Used to control the TestableCopyingManagerWorker.

        Its main role is to tell the manager thread when to unblock and how far to run.
        """

        def __init__(self, copying_worker):
            self.__copying_worker = copying_worker

        def perform_scan(self):
            """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
            the scan of the file system looking for new bytes in the log file.

            At this point, the CopyingManager should have a request ready to be sent.
            """
            # We guarantee it has scanned by making sure it has gone from sleeping to sending.
            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.SENDING,
                required_transition_state=TestableCopyingManagerWorker.SLEEPING,
            )

        def perform_pipeline_scan(self):
            """Tells the CopyingManager thread to advance far enough where it has performed the file system scan
            for the pipelined AddEventsRequest, if the manager is configured to send one..

            This is only valid to call immediately after a ``perform_scan``
            """
            # We guarantee it has done the pipeline scan by making sure it has gone through responding to sending.
            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.RESPONDING,
                required_transition_state=TestableCopyingManagerWorker.SENDING,
            )

        def wait_for_rpc(self):
            """Tells the CopyingManager thread to advance to the point where it has emulated sending an RPC.

            @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManager and a function that
                when invoked will return the passed in status message as the response to the AddEventsRequest.
            @rtype: (AddEventsRequest, func)
            """
            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.RESPONDING
            )
            request = self.__copying_worker.captured_request()

            def send_response(status_message):
                self.__copying_worker.set_response(status_message)
                self.__copying_worker.run_and_stop_at(
                    TestableCopyingManagerWorker.SLEEPING
                )

            return request, send_response

        def wait_for_full_iteration(self):
            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.SLEEPING,
            )

            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.SENDING,
                required_transition_state=TestableCopyingManagerWorker.SLEEPING,
            )

            self.__copying_worker.run_and_stop_at(
                TestableCopyingManagerWorker.SLEEPING,
                required_transition_state=TestableCopyingManagerWorker.SENDING,
            )

        def close_at_eof(self, filepath):
            """Tells the CopyingManager to mark the LogProcessor copying the specified path to close itself
            once all bytes have been copied up to Scalyr.  This can be used to remove LogProcessors for
            testing purposes.

            :param filepath: The path of the processor.
            :type filepath: six.text_type
            """
            # noinspection PyProtectedMember
            self.__copying_worker.log_processors[filepath].close_at_eof()

        def stop(self):
            self.__copying_worker.stop_worker()


class TestableCopyingManager(CopyingManager, BaseTestableCopyingManager):
    def __init__(self, configuration, monitors):
        from scalyr_agent.new_copying_manager import copying_manager

        original = copying_manager.CopyingManager
        copying_manager.CopyingManager = TestableCopyingManager
        CopyingManager.__init__(self, configuration, monitors)
        BaseTestableCopyingManager.__init__(self)

        copying_manager.CopyingManager = original

        from typing import List

        self._workers = self._workers  # type: List[TestableCopyingManager]

        self._workers_captured_requests = None

    def start_manager(self, scalyr_client=None, logs_initial_positions=None):
        """
        Overrides base class method, to initialize "scalyr_client" by default.
        """
        if scalyr_client is None:
            scalyr_client = dict(fake_client=True)
        super(TestableCopyingManager, self).start_manager(
            scalyr_client, logs_initial_positions=logs_initial_positions
        )

    def _workers_run_and_stop_at(self, stopping_at, required_transition_state=None):
        for worker in self._workers:
            worker.run_and_stop_at(
                stopping_at, required_transition_state=required_transition_state
            )

    def _workers_wait_for_rpc(self):
        requests = list()
        request_callbacks = list()
        for worker in self._workers:
            request, requrst_callback = worker.controller.wait_for_rpc()
            requests.append(request)
            request_callbacks.append(requrst_callback)
        return requests, request_callbacks

    def rrr(self, r):
        parsed_request = test_util.parse_scalyr_request(r.get_payload())

        lines = []

        if "events" in parsed_request:
            for event in parsed_request["events"]:
                if "attrs" in event:
                    attrs = event["attrs"]
                    if "message" in attrs:
                        lines.append(attrs["message"].strip())

        return lines

    def _sleep_but_awaken_if_stopped(self, seconds):

        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(BaseTestableCopyingManager.SENDING)
            responder_callbacks = list()
            requests = list()
            for worker in self._workers:
                r, rc = worker.controller.wait_for_rpc()
                lll = self.rrr(r)
                responder_callbacks.append(rc)
                requests.append(r)

            self._captured_request = requests
            self._responder_callbacks = responder_callbacks

        finally:
            self._test_state_cv.release()

        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(BaseTestableCopyingManager.RESPONDING)
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
            self._block_if_should_stop_at(BaseTestableCopyingManager.SLEEPING)
        finally:
            self._test_state_cv.release()

    def _sleep_but_awaken_if_stopped2(self, seconds):

        # return super(TestableCopyingManagerFacade, self)._sleep_but_awaken_if_stopped(seconds)
        # self._workers_run_and_stop_at(
        #     BaseTestableCopyingManager.SENDING,
        #     required_transition_state=BaseTestableCopyingManager.SENDING
        # )

        self._test_state_cv.acquire()

        try:
            self._block_if_should_stop_at(BaseTestableCopyingManager.SENDING)
        finally:
            self._test_state_cv.release()
            requests = list()
            responder_callbacks = list()
            for worker in self._workers:
                worker.run_and_stop_at(BaseTestableCopyingManager.SENDING)
                # request, responder_callback = worker.controller.wait_for_rpc()
                # requests.append(request)
                # responder_callbacks.append(responder_callback)

            # self._captured_request = requests
            # self._responder_callbacks = responder_callbacks

            def emit_responses():
                self._test_state_cv.acquire()
                try:
                    self._block_if_should_stop_at(TestableCopyingManager.RESPONDING)

                    # Use the pending response if there is one.  Otherwise, we just say "success" which means all add event
                    # requests will just be processed.
                    result = self._pending_response
                    self._pending_response = None
                finally:
                    self._test_state_cv.release()

                for worker in self._workers:
                    worker.set_responce()

                if result is not None:
                    return result, 0, "fake"
                else:
                    return "success", 0, "fake"

            self._test_state_cv.release()

        # emit_responses()
        # r = self._pending_response
        # for responder_callback in responder_callbacks:
        #     responder_callback(result)

        # self._test_state_cv.acquire()
        # try:
        #     self._block_if_should_stop_at(BaseTestableCopyingManager.RESPONDING)
        #
        #
        # finally:
        #     self._test_state_cv.release()

        self._test_state_cv.acquire()
        try:
            self._block_if_should_stop_at(BaseTestableCopyingManager.SLEEPING)
        finally:
            self._test_state_cv.release()
        #
        #
        #
        # self._workers_run_and_stop_at(
        #     BaseTestableCopyingManager.RESPONDING,
        #     required_transition_state=BaseTestableCopyingManager.SENDING
        # )
        # self._block_if_should_stop_at(BaseTestableCopyingManager.RESPONDING)
        # self._workers_run_and_stop_at(
        #     BaseTestableCopyingManager.SLEEPING,
        #     required_transition_state=BaseTestableCopyingManager.RESPONDING
        # )

    # def _scan_for_new_logs_if_necessary(
    #         self,
    #         current_time=None,
    #         checkpoints=None,
    #         logs_initial_positions=None,
    #         copy_at_index_zero=False,
    # ):
    #     pass

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops the manager's thread.

        @param wait_on_join:  Whether or not to wait on thread to finish.
        @param join_timeout:  The number of seconds to wait on the join.
        @type wait_on_join: bool
        @type join_timeout: float
        @return:
        @rtype:
        """
        # We need to do some extra work here in case the CopyingManager thread is currently in a blocked state.
        # We need to tell it to keep running.
        self._test_state_cv.acquire()
        self._test_stop_state = None
        self._test_state_cv.notifyAll()
        self._test_state_cv.release()

        CopyingManage.stop_manager(
            self, wait_on_join=wait_on_join, join_timeout=join_timeout
        )

    class TestController(object):
        """Used to control the TestableCopyingManager.

        Its main role is to tell the manager thread when to unblock and how far to run.
        """

        def __init__(self, copying_manager):
            self.__copying_manager = copying_manager

        def perform_scan(self):
            """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
            the scan of the file system looking for new bytes in the log file.

            At this point, the CopyingManager should have a request ready to be sent.
            """

            # We guarantee it has scanned by making sure it has gone from sleeping to sending.
            self.__copying_manager.run_and_stop_at(
                TestableCopyingManager.SENDING,
                required_transition_state=TestableCopyingManager.SLEEPING,
            )

            for worker in self.__copying_manager._workers:
                worker.controller.perform_scan()

        def perform_pipeline_scan(self):
            """Tells the CopyingManager thread to advance far enough where it has performed the file system scan
            for the pipelined AddEventsRequest, if the manager is configured to send one..

            This is only valid to call immediately after a ``perform_scan``
            """
            # We guarantee it has done the pipeline scan by making sure it has gone through responding to sending.
            self.__copying_manager.run_and_stop_at(
                TestableCopyingManager.RESPONDING,
                required_transition_state=TestableCopyingManager.SENDING,
            )

        def wait_for_rpc(self):
            """Tells the CopyingManager thread to advance to the point where it has emulated sending an RPC.

            @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManager and a function that
                when invoked will return the passed in status message as the response to the AddEventsRequest.
            @rtype: (AddEventsRequest, func)
            """

            # requests = list()
            # responder_callbacks = list()
            # for worker in self.__copying_manager._workers:
            #     request, responder_callback = worker.controller.wait_for_rpc()
            #     requests.append(request)
            #     responder_callbacks.append(responder_callback)

            self.__copying_manager.run_and_stop_at(TestableCopyingManager.RESPONDING)
            requests = self.__copying_manager.captured_request()

            def send_response(status_message):

                self.__copying_manager.set_response(status_message)
                self.__copying_manager.run_and_stop_at(TestableCopyingManager.SLEEPING)

            return requests, send_response

        def close_at_eof(self, filepath):
            """Tells the CopyingManager to mark the LogProcessor copying the specified path to close itself
            once all bytes have been copied up to Scalyr.  This can be used to remove LogProcessors for
            testing purposes.

            :param filepath: The path of the processor.
            :type filepath: six.text_type
            """
            # noinspection PyProtectedMember
            self.__copying_manager._CopyingManager__log_paths_being_processed[
                filepath
            ].close_at_eof()

        def stop(self):
            self.__copying_manager.stop_manager()
