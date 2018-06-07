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
import unittest

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
from scalyr_agent.test_base import ScalyrTestCase
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
        return Configuration(self.__config_file, default_paths)


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

    def __create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        logs_json_array = JsonArray()

        for entry in configuration_logs_entry:
            logs_json_array.add(JsonObject(content=entry))

        fp = open(config_file, 'w')
        fp.write(json_lib.serialize(JsonObject(api_key='fake', logs=logs_json_array)))
        fp.close()

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        config = Configuration(config_file, default_paths)
        config.parse()

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

    @unittest.skip("@czerwin to investigate")
    def test_single_log_file(self):
        controller = self.__create_test_instance()
        self.__append_log_lines('First line', 'Second line')
        (request, responder_callback) = controller.wait_for_rpc()

        lines = self.__extract_lines(request)
        self.assertEquals(2, len(lines))
        self.assertEquals('First line', lines[0])
        self.assertEquals('Second line', lines[1])

        responder_callback('success')

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

    @unittest.skip("@czerwin to investigate")
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

        config = Configuration(config_file, default_paths)
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
    def __init__(self, configuration, monitors):
        CopyingManager.__init__(self, configuration, monitors)
        # Approach:  We will override key methods of CopyingManager, blocking them from returning until the controller
        # tells it to proceed.  This allows us to then do things like write new log lines while the CopyingManager is
        # blocked.   Coordinating the communication between the two threads is done using two condition variables.
        # We changed the CopyingManager to block in three places: while it is sleeping before it starts a new loop,
        # when it invokes ``_send_events`` to send a new request, and when it blocks to receive the response.
        # These three states or referred to as "sleeping", "blocked_on_send", "blocked_on_receive".
        #
        # This cv protects all of the variables written by the CopyingManager thread.
        self.__test_state_cv = threading.Condition()
        # Which state the CopyingManager is currently blocked in -- "sleeping", "blocked_on_send", "blocked_on_receive"
        self.__test_state = None
        # The number of times the CopyingManager has blocked.
        self.__test_state_changes = 0
        # Whether or not the CopyingManager should stop.
        self.__test_stopping = False
        # Written by CopyingManager.  The last AddEventsRequest request passed into ``_send_events``.
        self.__captured_request = None
        # Protected by __test_state_cv.  The status message to return for the next call to ``_send_events``.
        self.__pending_response = None

        # This cv protects __advance_requests and is used mainly by the testing thread.
        self.__advance_requests_cv = threading.Condition()
        # This is incremented everytime the controller wants the CopyingManager to advance to the next blocking state,
        # regardless of which state it is in.
        self.__advance_requests = 0

        self.__controller = TestableCopyingManager.TestController(self)

    @property
    def controller(self):
        return self.__controller

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Blocks the CopyingManager thread until the controller tells it to proceed.
        """
        self.__test_state_cv.acquire()
        self.__wait_until_advance_received('sleeping')
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
        self.__wait_until_advance_received('blocked_on_send')
        self.__captured_request = add_events_task.add_events_request
        self.__test_state_cv.release()

        # Create a method that we can return that will (when invoked) return the response
        def emit_response():
            # Block on return the response until the state is advanced.
            self.__test_state_cv.acquire()
            self.__wait_until_advance_received('blocked_on_receive')

            # Use the pending response if there is one.  Otherwise, we just say "success" which means all add event
            # requests will just be processed.
            result = self.__pending_response
            self.__pending_response = None
            self.__test_state_cv.release()

            if result is not None:
                return result, 0, 'fake'
            else:
                return 'success', 0, 'fake'

        return emit_response

    def __wait_until_advance_received(self, new_state):
        """Helper method for blocking the thread until the controller thread has indicated this one should advance
        to its next state.

        You must be holding the self.__test_state_cv lock to invoke this method.

        @param new_state: The name of the blocking state the CopyingManager is in until it is advanced.
        @type new_state: str
        """
        if self.__test_stopping:
            return
        # We are about to block, so be sure to increment the count.  We make use of this to detect when state changes
        # are made.  This is broadcasted to the controller thread.
        self.__test_state_changes += 1
        self.__test_state = new_state
        self.__test_state_cv.notifyAll()
        self.__test_state_cv.release()

        # Now we have to wait until we see another advance request.  To do that, we just note when the number of
        # advances has increased.  Of course, we need to get the __advance_requests_cv lock to look at that var.
        self.__advance_requests_cv.acquire()
        original_advance_requests = self.__advance_requests

        while self.__advance_requests == original_advance_requests:
            self.__advance_requests_cv.wait()
        self.__advance_requests_cv.release()

        # Get the lock again so that we have it when the method returns.
        self.__test_state_cv.acquire()
        self.__test_state = 'running'

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

    def advance_until(self, final_state):
        """Instructs the CopyingManager thread to keep advancing through its blocking states until it reaches the
        named one.

        @param final_state:  The name of the state to wait for (such as "sleeping", "blocked_on_receive", etc.
        @type final_state: str
        """
        self.__test_state_cv.acquire()
        original_count = self.__test_state_changes

        # We have to keep incrementing the __advanced_requests count so that the copying manager thread keeps
        # advancing.  We wait on the test_state_cv because everytime the CopyingManager blocks, it notifies that cv.
        while self.__test_state_changes <= original_count or self.__test_state != final_state:
            self.__advance_requests_cv.acquire()
            self.__advance_requests += 1
            self.__advance_requests_cv.notifyAll()
            self.__advance_requests_cv.release()
            self.__test_state_cv.wait()

        self.__test_state_cv.release()

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
        # We need to tell it to advance.
        self.__test_state_cv.acquire()
        self.__test_stopping = True
        self.__test_state_cv.release()

        self.__advance_requests_cv.acquire()
        self.__advance_requests += 1
        self.__advance_requests_cv.notifyAll()
        self.__advance_requests_cv.release()

        CopyingManager.stop_manager(self, wait_on_join=wait_on_join, join_timeout=join_timeout)

    @property
    def test_state(self):
        """
        @return:  Returns the name of the state the CopyingManager thread is currently blocked in, such as
            "sleeping", "blocked_on_send", "blocked_on_receive".
        @rtype: str
        """
        self.__test_state_cv.acquire()
        try:
            return self.__test_state
        finally:
            self.__test_state_cv.release()

    class TestController(object):
        """Used to control the TestableCopyingManager.

        Its main role is to tell the manager thread when to unblock and how far to run.
        """
        def __init__(self, copying_manager):
            self.__copying_manager = copying_manager
            copying_manager.start_manager(dict(fake_client=True))

            # To do a proper initialization where the copying manager has scanned the current log file and is ready
            # for the next loop, we let it go all the way through the loop once and wait in the sleeping state.
            self.__copying_manager.advance_until('sleeping')

        def perform_scan(self):
            """Tells the CopyingManager thread to go through the process loop until far enough where it has performed
            the scan of the file system looking for new bytes in the log file.

            At this point, the CopyingManager should have a request ready to be sent.
            """
            self.__copying_manager.captured_request()
            self.__copying_manager.advance_until('blocked_on_send')

        def perform_pipeline_scan(self):
            """Tells the CopyingManager thread to advance far enough where it has performed the file system scan
            for the pipelined AddEventsRequest, if the manager is configured to send one..

            This is only valid to call immediately after a ``perform_scan``
            """
            self.__copying_manager.advance_until('blocked_on_receive')

        def wait_for_rpc(self):
            """Tells the CopyingManager thread to advance to the point where it has emulated sending an RPC.

            @return:  A tuple containing the AddEventsRequest that was sent by the CopyingManager and a function that
                when invoked will return the passed in status message as the response to the AddEventsRequest.
            @rtype: (AddEventsRequest, func)
            """
            if self.__copying_manager.test_state != 'blocked_on_receive':
                self.__copying_manager.advance_until('blocked_on_receive')
            request = self.__copying_manager.captured_request()

            def send_response(status_message):
                self.__copying_manager.set_response(status_message)
                self.__copying_manager.advance_until('sleeping')

            return request, send_response

        def stop(self):
            self.__copying_manager.stop_manager()


class FakeMonitor(object):
    def __init__(self, monitor_log_config):
        self.module_name = 'fake_monitor'
        self.log_config = monitor_log_config

    def set_log_watcher(self, log_watcher):
        pass
