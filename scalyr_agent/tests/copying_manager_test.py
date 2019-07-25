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
import threading

__author__ = 'czerwin@scalyr.com'


import os
import tempfile

import logging
import sys
import time

root = logging.getLogger()
root.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
root.addHandler(ch)

from scalyr_agent.configuration import Configuration
from scalyr_agent.copying_manager import CopyingParameters, CopyingManager
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.scalyr_client import AddEventsRequest
from scalyr_agent.test_base import skip, ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent import json_lib

ONE_MB = 1024 * 1024


class CopyingParamsTest(ScalyrTestCase):
    def setUp(self):
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, 'agentConfig.json')
        self.__config_fragments_dir = os.path.join(self.__config_dir, 'configs.d')
        os.makedirs(self.__config_fragments_dir)

        fp = open(self.__config_file, 'w')
        fp.write('{api_key: "fake"}')
        fp.close()

        config = self.__create_test_configuration_instance()
        config.parse()
        self.test_params = CopyingParameters(config)

    def test_initial_settings(self):
        self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MB)
        self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_no_events_being_sent(self):
        for i in range(0, 5):
            self.test_params.update_params('success', 0)
            self.assertEquals(self.test_params.current_bytes_allowed_to_send, ONE_MB)
            self.assertEquals(self.test_params.current_sleep_interval, 5.0)

    def test_small_events_being_sent(self):
        self.test_params.current_sleep_interval = 1
        self._run('success', 10 * 1024, [1.5, ONE_MB], [2.25, ONE_MB], [3.375, ONE_MB], [5, ONE_MB])

    def test_too_many_events_being_sent(self):
        self.test_params.current_sleep_interval = 5

        self._run('success', 200 * 1024, [3.0, ONE_MB], [1.8, ONE_MB], [1.08, ONE_MB], [1, ONE_MB])

    def test_request_too_big(self):
        self.test_params.current_sleep_interval = 1

        self.test_params.update_params('requestTooLarge', 300 * 1024)
        self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, 150 * 1024)

        self.test_params.update_params('requestTooLarge', 150 * 1024)
        self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, 100 * 1024)

    def test_error_back_off(self):
        self.test_params.current_sleep_interval = 3
        self._run('error', 200 * 1024, [4.5, ONE_MB], [6.75, ONE_MB], [10.125, ONE_MB], [15.1875, ONE_MB],
                           [22.78125, ONE_MB], [30, ONE_MB])

    def _run(self, status, bytes_sent, *expected_sleep_interval_allowed_bytes):
        """Verifies that when test_params is updated with the specified status and bytes sent the current sleep
        interval and allowed bytes is updated to the given values.

        This will call test_params.update_params N times where N is the number of additional arguments supplied.
        After the ith invocation of test_params.update_params, the values for the current_sleep_interval and
        current_bytes_allowed_to_send will be checked against the ith additional parameter.

        @param status: The status to use when invoking test_params.update_params.
        @param bytes_sent: The number of bytes sent to use when invoking test_params.update_params.
        @param expected_sleep_interval_allowed_bytes: A variable number of two element arrays where the first element
            is the expected value for current_sleep_interval and the second is the expected value of
            current_bytes_allowed_to_send. Each subsequent array represents what those values should be after invoking
            test_params.update_param again.
        """
        for expected_result in expected_sleep_interval_allowed_bytes:
            self.test_params.update_params(status, bytes_sent)
            self.assertAlmostEquals(self.test_params.current_sleep_interval, expected_result[0])
            self.assertAlmostEquals(self.test_params.current_bytes_allowed_to_send, expected_result[1])

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config['path']

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config['module']
            self.config = config
            self.log_config = {'path': self.module_name.split('.')[-1] + '.log'}

    def __create_test_configuration_instance(self):

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')
        return Configuration(self.__config_file, default_paths, None)


class CopyingManagerInitializationTest(ScalyrTestCase):

    def test_from_config_file(self):
        test_manager = self.__create_test_instance([
            {
                'path': '/tmp/hi.log'
            }
        ], [])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/tmp/hi.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/var/log/scalyr-agent-2/agent.log')

    def test_from_monitors(self):
        test_manager = self.__create_test_instance([
        ], [
            {
                'path': '/tmp/hi_monitor.log',
            }
        ])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/tmp/hi_monitor.log')
        self.assertEquals(test_manager.log_matchers[1].config['attributes']['parser'], 'agent-metrics')

    def test_multiple_monitors_for_same_file(self):
        test_manager = self.__create_test_instance([
        ], [
            {'path': '/tmp/hi_monitor.log'},
            {'path': '/tmp/hi_monitor.log'},
            {'path': '/tmp/hi_second_monitor.log'}
        ])
        self.assertEquals(len(test_manager.log_matchers), 3)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/tmp/hi_monitor.log')
        self.assertEquals(test_manager.log_matchers[1].config['attributes']['parser'], 'agent-metrics')
        self.assertEquals(test_manager.log_matchers[2].config['path'], '/tmp/hi_second_monitor.log')
        self.assertEquals(test_manager.log_matchers[2].config['attributes']['parser'], 'agent-metrics')

    def test_monitor_log_config_updated(self):
        test_manager = self.__create_test_instance([
        ], [
            {'path': 'hi_monitor.log'},
        ])
        self.assertEquals(len(test_manager.log_matchers), 2)
        self.assertEquals(test_manager.log_matchers[0].config['path'], '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(test_manager.log_matchers[1].config['path'], '/var/log/scalyr-agent-2/hi_monitor.log')

        # We also verify the monitor instance itself's log config object was updated to have the full path.
        self.assertEquals(self.__monitor_fake_instances[0].log_config['path'], '/var/log/scalyr-agent-2/hi_monitor.log')

    def test_remove_log_path_with_non_existing_path(self):
        test_manager = self.__create_test_instance([
        ], [
            {'path': 'test.log'},
        ])
        # check that removing a non-existent path runs without throwing an exception
        test_manager.remove_log_path( 'test_monitor', 'blahblah.log' )

    def __create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        logs_json_array = JsonArray()
        for entry in configuration_logs_entry:
            logs_json_array.add(JsonObject(content=entry))

        config = ScalyrTestUtils.create_configuration(extra_toplevel_config={'logs': logs_json_array})

        self.__monitor_fake_instances = []
        for monitor_log_config in monitors_log_configs:
            self.__monitor_fake_instances.append(FakeMonitor(monitor_log_config))

        # noinspection PyTypeChecker
        return CopyingManager(config, self.__monitor_fake_instances)


class CopyingManagerEnd2EndTest(ScalyrTestCase):

    def setUp(self):
        self._controller = None

    def tearDown(self):
        if self._controller is not None:
            self._controller.stop()

    def test_single_log_file(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('success')

    def test_multiple_scans_of_log_file(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('success')

        self.__append_log_lines('Third line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals('Third line', lines[0])

    def test_normal_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('error')

        self.__append_log_lines('Third line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

    def test_drop_request_due_to_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('discardBuffer')

        self.__append_log_lines('Third line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals('Third line', lines[0])

    def test_request_too_large_error(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('requestTooLarge')

        self.__append_log_lines('Third line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(3, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])
        self.assertEquals('Third line', lines[2])

    def test_pipelined_requests(self):
        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines('First line', 'Second line')

        controller.perform_scan()
        self.__append_log_lines('Third line')
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('success')

        (request, responder_callback) = controller.wait_for_rpc()

        self.assertTrue(self.__was_pipelined(request))

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals('Third line', lines[0])

        responder_callback('success')

    def test_pipelined_requests_with_normal_error(self):
        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines('First line', 'Second line')

        controller.perform_scan()
        self.__append_log_lines('Third line')
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('error')

        (request, responder_callback) = controller.wait_for_rpc()
        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('success')

        (request, responder_callback) = controller.wait_for_rpc()

        self.assertTrue(self.__was_pipelined(request))

        lines = self.__extract_lines(request)
        self.assertEquals(1, len(lines))
        self.assertEquals('Third line', lines[0])

        responder_callback('success')

    def test_pipelined_requests_with_retry_error(self):
        controller = self.__create_test_instance(use_pipelining=True)
        self.__append_log_lines('First line', 'Second line')

        controller.perform_scan()
        self.__append_log_lines('Third line')
        controller.perform_pipeline_scan()
        (request, responder_callback) = controller.wait_for_rpc()

        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('requestTooLarge')

        (request, responder_callback) = controller.wait_for_rpc()
        self.assertFalse(self.__was_pipelined(request))

        lines = self.__extract_lines(request)

        self.assertEquals(3, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])
        self.assertEquals('Third line', lines[2])

        responder_callback('success')

    def __extract_lines(self, request):
        parsed_request = json_lib.parse(request.get_payload())

        lines = []

        if 'events' in parsed_request:
            for event in parsed_request.get_json_array('events'):
                if 'attrs' in event:
                    attrs = event.get_json_object('attrs')
                    if 'message' in attrs:
                        lines.append(attrs.get_string('message').strip())

        return lines

    def __was_pipelined(self, request):
        return 'pipelined=1.0' in request.get_timing_data()

    def __create_test_instance(self, use_pipelining=False):
        tmp_dir = tempfile.mkdtemp()
        config_dir = os.path.join(tmp_dir, 'config')
        data_dir = os.path.join(tmp_dir, 'data')
        log_dir = os.path.join(tmp_dir, 'log')

        os.mkdir(data_dir)
        os.mkdir(config_dir)
        os.mkdir(log_dir)

        self.__test_log_file = os.path.join(tmp_dir, 'test.log')
        fp = open(self.__test_log_file, 'w')
        fp.close()

        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        logs_json_array = JsonArray()
        logs_json_array.add(JsonObject(path=self.__test_log_file))

        pipeline_threshold = 1.1
        if use_pipelining:
            pipeline_threshold = 0.0

        fp = open(config_file, 'w')
        fp.write(json_lib.serialize(JsonObject(api_key='fake', logs=logs_json_array,
                                               pipeline_threshold=pipeline_threshold)))
        fp.close()

        default_paths = DefaultPaths(log_dir, config_file, data_dir)

        config = Configuration(config_file, default_paths, None)
        config.parse()

        # noinspection PyTypeChecker
        self._controller = TestableCopyingManager(config, []).controller
        return self._controller

    def __append_log_lines(self, *args):
        fp = open(self.__test_log_file, 'a')
        for l in args:
            fp.write(l)
            fp.write('\n')
        fp.close()


class TestableCopyingManager(CopyingManager):
    """An instrumented version of the CopyingManager which allows intercepting of requests sent, control when
    the manager processes new logs, etc.

    This allows for end-to-end testing of the core of the CopyingManager.

    Doing this right is a bit complicated because the CopyingManager runs in its own thread.

    To actually control the copying manager, use the TestController object returned by ``controller``.
    """
    # The different points at which the CopyingManager can be stopped.  See below.
    SLEEPING = 'sleeping'
    SENDING = 'sending'
    RESPONDING = 'responding'

    # To prevent tests from hanging indefinitely, wait a maximum amount of time before giving up on some test condition.
    WAIT_TIMEOUT = 5.0

    def __init__(self, configuration, monitors):
        CopyingManager.__init__(self, configuration, monitors)
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
        self.__test_state_cv = threading.Condition()
        # Which state the CopyingManager should block in -- "sleeping", "sending", "responding"
        # We initialize it to a special value "all" so that it stops as soon the CopyingManager starts up.
        self.__test_stop_state = 'all'
        # If not none, a state the test must pass through before it tries to stop at `__test_stop_state`.
        # If this transition is not observed by the time it does get to the stop state, an assertion is thrown.
        self.__test_required_transition = None
        # Whether or not the CopyingManager is stopped at __test_stop_state.
        self.__test_is_stopped = False
        # Written by CopyingManager.  The last AddEventsRequest request passed into ``_send_events``.
        self.__captured_request = None
        # Protected by __test_state_cv.  The status message to return for the next call to ``_send_events``.
        self.__pending_response = None

        self.__controller = TestableCopyingManager.TestController(self)

    @property
    def controller(self):
        return self.__controller

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Blocks the CopyingManager thread until the controller tells it to proceed.
        """
        self.__test_state_cv.acquire()
        try:
            self.__block_if_should_stop_at(TestableCopyingManager.SLEEPING)
        finally:
            self.__test_state_cv.release()

    def _create_add_events_request(self, session_info=None, max_size=None):
        # Need to override this to return an AddEventsRequest even though we don't have a real scalyr client instance.
        if session_info is None:
            body = JsonObject(server_attributes=session_info, token='fake')
        else:
            body = JsonObject(token='fake')

        return AddEventsRequest(body, max_size=max_size)

    def _send_events(self, add_events_task):
        """Captures ``add_events_task`` and emulates sending an AddEventsTask.

        This method will not return until the controller tells it to advance to the next state.
        """
        # First, block even returning from this method until the controller advances us.
        self.__test_state_cv.acquire()
        try:
            self.__block_if_should_stop_at(TestableCopyingManager.SENDING)
            self.__captured_request = add_events_task.add_events_request
        finally:
            self.__test_state_cv.release()

        # Create a method that we can return that will (when invoked) return the response
        def emit_response():
            # Block on return the response until the state is advanced.
            self.__test_state_cv.acquire()
            try:
                self.__block_if_should_stop_at(TestableCopyingManager.RESPONDING)

                # Use the pending response if there is one.  Otherwise, we just say "success" which means all add event
                # requests will just be processed.
                result = self.__pending_response
                self.__pending_response = None
            finally:
                self.__test_state_cv.release()

            if result is not None:
                return result, 0, 'fake'
            else:
                return 'success', 0, 'fake'

        return emit_response

    def captured_request(self):
        """Returns the last request that was passed into ``_send_events`` by the CopyingManager, or None if there
        wasn't any.

        This will also reset the captured request to None so the returned request won't be returned twice.

        @return: The last request
        @rtype: AddEventsRequest
        """
        self.__test_state_cv.acquire()
        try:
            result = self.__captured_request
            self.__captured_request = None
            return result
        finally:
            self.__test_state_cv.release()

    def set_response(self, status_message):
        """Sets the status_message to return as the response for the next AddEventsRequest.

        @param status_message: The status message
        @type status_message: str
        """
        self.__test_state_cv.acquire()
        self.__pending_response = status_message
        self.__test_state_cv.release()

    def __block_if_should_stop_at(self, current_point):
        """Invoked by the CopyManager thread to report it has transitioned to the specified state and will block if
        `run_and_stop_at` has been invoked with `current_point` as the stopping point.

        @param current_point: The point reached by the CopyingManager thread, only valid values are
            `SLEEPING`, `SENDING`, and `RESPONDING`.
        @type current_point: str
        """
        # If we are passing through the required_transition state, consume it to signal we have accomplished
        # the transition.
        if current_point == self.__test_required_transition:
            self.__test_required_transition = None

        # Block if it has been requested that we block here.  Note, __test_stop_state can only be:
        # 'all'  -- indicating it should stop at the first state it sees.
        # None -- indicating the test is shutting down and the CopyingManger thread should just run until it finishes
        # One of `SLEEPING`, `SENDING`, and `RESPONDING` -- indicating where we should next block the CopyingManager.
        start_time = time.time()
        while self.__test_stop_state == 'all' or current_point == self.__test_stop_state:
            self.__test_is_stopped = True
            if self.__test_required_transition is not None:
                raise AssertionError('Stopped at %s state but did not transition through %s' % (
                    current_point, self.__test_required_transition))
            # This notifies any threads waiting in the `run_and_stop_at` method.  They would be blocking waiting for
            # the CopyingManager thread to stop at this point.
            self.__test_state_cv.notifyAll()
            # We need to wait until some other state is set as the stop state.  The `notifyAll` in `run_and_stop_at`
            # method will wake us up.
            self.__test_state_cv_wait_with_timeout(start_time)

        self.__test_is_stopped = False

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

        @type stopping_at: str
        @type required_transition_state: str or None
        """
        self.__test_state_cv.acquire()
        try:
            # Just to avoid mistakes in testing, make sure we successfully consumed any require transitions before
            # we tell it to stop anywhere else.
            if self.__test_required_transition is not None:
                raise AssertionError('Setting new stop state %s with pending required transition %s' % (
                    stopping_at, self.__test_required_transition))
            # If we are already in the required_transition_state, consume it.
            if self.__test_is_stopped and self.__test_stop_state == required_transition_state:
                self.__test_required_transition = None
            else:
                self.__test_required_transition = required_transition_state

            if self.__test_is_stopped and self.__test_stop_state == stopping_at:
                return

            self.__test_stop_state = stopping_at
            self.__test_is_stopped = False
            # This will wake up threads in `__block_if_should_stop_at` which are waiting for a new stopping point.
            self.__test_state_cv.notifyAll()

            start_time = time.time()
            # Wait until we get to this point.
            while not self.__test_is_stopped:
                # This will be woken up by the notify in `__block_if_should_stop_at` method.
                self.__test_state_cv_wait_with_timeout(start_time)
        finally:
            self.__test_state_cv.release()

    def __test_state_cv_wait_with_timeout(self, start_time):
        """Waits on the `__test_state_cv` condition variable, but will also throw an AssertionError if the wait
        time exceeded the `start_time` plus `WAIT_TIMEOUT`.

        @param start_time:  The start time when we first began waiting on this condition, in seconds past epoch.
        @type start_time: Number
        """
        deadline = start_time + TestableCopyingManager.WAIT_TIMEOUT
        self.__test_state_cv.wait(timeout=(deadline - time.time()) + 0.5)
        if time.time() > deadline:
            raise AssertionError('Deadline exceeded while waiting on condition variable')

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
        self.__test_state_cv.acquire()
        self.__test_stop_state = None
        self.__test_state_cv.notifyAll()
        self.__test_state_cv.release()

        CopyingManager.stop_manager(self, wait_on_join=wait_on_join, join_timeout=join_timeout)

    class TestController(object):
        """Used to control the TestableCopyingManager.

        Its main role is to tell the manager thread when to unblock and how far to run.
        """
        def __init__(self, copying_manager):
            self.__copying_manager = copying_manager
            copying_manager.start_manager(dict(fake_client=True))
            # To do a proper initialization where the copying manager has scanned the current log file and is ready
            # for the next loop, we let it go all the way through the loop once and wait in the sleeping state.
            copying_manager.run_and_stop_at(TestableCopyingManager.SLEEPING)

        def perform_scan(self):
            """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
            the scan of the file system looking for new bytes in the log file.

            At this point, the CopyingManager should have a request ready to be sent.
            """
            # We guarantee it has scanned by making sure it has gone from sleeping to sending.
            self.__copying_manager.run_and_stop_at(TestableCopyingManager.SENDING,
                                                   required_transition_state=TestableCopyingManager.SLEEPING)

        def perform_pipeline_scan(self):
            """Tells the CopyingManager thread to advance far enough where it has performed the file system scan
            for the pipelined AddEventsRequest, if the manager is configured to send one..

            This is only valid to call immediately after a ``perform_scan``
            """
            # We guarantee it has done the pipeline scan by making sure it has gone through responding to sending.
            self.__copying_manager.run_and_stop_at(TestableCopyingManager.RESPONDING,
                                                   required_transition_state=TestableCopyingManager.SENDING)

        def wait_for_rpc(self):
            """Tells the CopyingManager thread to advance to the point where it has emulated sending an RPC.

            @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManager and a function that
                when invoked will return the passed in status message as the response to the AddEventsRequest.
            @rtype: (AddEventsRequest, func)
            """
            self.__copying_manager.run_and_stop_at(TestableCopyingManager.RESPONDING)
            request = self.__copying_manager.captured_request()

            def send_response(status_message):
                self.__copying_manager.set_response(status_message)
                self.__copying_manager.run_and_stop_at(TestableCopyingManager.SLEEPING)

            return request, send_response

        def stop(self):
            self.__copying_manager.stop_manager()


class FakeMonitor(object):
    def __init__(self, monitor_log_config):
        self.module_name = 'fake_monitor'
        self.log_config = monitor_log_config

    def set_log_watcher(self, log_watcher):
        pass
