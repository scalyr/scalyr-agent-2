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


__author__ = 'czerwin@scalyr.com'


import logging
import os
import re
import tempfile
import threading
import time

from collections import Counter

import scalyr_agent.util as scalyr_util

from scalyr_agent.configuration import Configuration
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent.scalyr_logging import AgentLogger
from scalyr_agent import json_lib

from scalyr_agent.test_base import ScalyrTestCase


class MonitorsManagerTest(ScalyrTestCase):
    def test_single_module(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            }
        ], [])
        self.assertEquals(len(test_manager.monitors), 1)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor()')

    def test_multiple_modules(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
        ], [])

        self.assertEquals(len(test_manager.monitors), 2)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor(1)')
        self.assertEquals(test_manager.monitors[1].monitor_name, 'test_monitor(2)')

    def test_module_with_id(self):
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'id': 'first',
                'gauss_mean': 0
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            },
        ], [])
        self.assertEquals(len(test_manager.monitors), 2)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor(first)')
        self.assertEquals(test_manager.monitors[1].monitor_name, 'test_monitor(2)')

    def test_user_agent_polling(self):
        """Test polling of user-agent fragments and invocation of the callback (only on change)

        A MonitorsManager + 2 monitors are started (each has their own threads).
        1 monitor returns non-empty frags. 1 returns None.
        We then verify that the callback is invoked correctly, only if the fragments change.

        Notes:
        - FakeClocks are used to avoid having to wait for thread loops.
        - A FakeAgentLogger is defined so we can modify local test state
        - Even though this test could have been broken up into 2 smaller ones, it is kept as one to minimize overhead
            time taken by stop_manager()
        """
        counter = Counter()
        test_frag = 'some_frag'
        poll_interval = 30

        # Create MonitorsManager + 2 monitors. Set each to daemon otherwise unit test doesn't terminate
        test_manager = self.__create_test_instance([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0,
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0,
            },
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0,
            },
        ], [], extra_toplevel_config={'user_agent_refresh_interval': poll_interval})
        self.assertEquals(test_manager._user_agent_refresh_interval, 30)  # ensure config setting works
        self.assertEquals(len(test_manager.monitors), 3)
        patched_monitor_0 = test_manager.monitors[0]
        patched_monitor_1 = test_manager.monitors[1]
        unpatched_monitor = test_manager.monitors[2]

        # Fake the clock to fast-forward MonitorsManager sleep loop
        fake_clock = scalyr_util.FakeClock()
        for obj in [test_manager, patched_monitor_0, unpatched_monitor]:
            obj._run_state = scalyr_util.RunState(fake_clock=fake_clock)

        class FragmentPolls(object):
            def __init__(self):
                self.__polls = 0
                self.__condition = threading.Condition()

            def count(self):
                self.__condition.acquire()
                try:
                    return self.__polls
                finally:
                    self.__condition.release()

            def increment(self):
                self.__condition.acquire()
                try:
                    self.__polls += 1
                    self.__condition.notifyAll()
                finally:
                    self.__condition.release()

            def wait_for_increment(self, old_count, timeout=None):
                remaining = timeout
                self.__condition.acquire()
                try:
                    while self.__polls == old_count and remaining > 0:
                        t1 = time.time()
                        self.__condition.wait(remaining)
                        remaining -= time.time() - t1
                finally:
                    self.__condition.release()

            def poll_until_target(self, target_polls, maxwait):
                """Blocks until n fragment polls are simulated by the MonitorsManager, or an absolute cutoff time.
                whichever comes first.

                @param target_polls: Number of polls to reach
                @param maxwait: Time (seconds) to wait for target to be reached
                @return: True if number of polls reaches target_polls, else False
                """
                deadline = time.time() + maxwait
                while self.count() < target_polls and time.time() < deadline:
                    fake_clock.block_until_n_waiting_threads(1)  # wait for monitor thread loop to complete
                    old_count = self.count()
                    fake_clock.advance_time(increment_by=poll_interval)
                    self.wait_for_increment(old_count, timeout=deadline-time.time())

                return self.count() == target_polls

        fragment_polls = FragmentPolls()

        # Mock the function that returns user_agent_fragment (normally invoked on a Monitor)
        def mock_get_user_agent_fragment():
            # Will be called on 2 patched monitors concurrently
            fragment_polls.increment()
            return test_frag
        for mon in [patched_monitor_0, patched_monitor_1]:
            mon.get_user_agent_fragment = mock_get_user_agent_fragment
            self.assertEquals(mon.get_user_agent_fragment(), test_frag)  # monkey patched
        self.assertEquals(unpatched_monitor.get_user_agent_fragment(), None)  # not patched

        # Mock the callback (that would normally be invoked on ScalyrClientSession)
        # Check that the exact fragment returned by the 2 patched monitors are deduplicated.
        def augment_user_agent(fragments):
            counter['callback_invocations'] += 1
            self.assertEquals(fragments, [test_frag])
        test_manager.set_user_agent_augment_callback(augment_user_agent)

        # Override Agent Logger to prevent writing to disk
        class FakeAgentLogger(AgentLogger):
            def __init__(self, name):
                super(FakeAgentLogger, self).__init__(name)
                if not len(self.handlers):
                    self.addHandler(logging.NullHandler())

        for monitor in [patched_monitor_0, patched_monitor_1, unpatched_monitor]:
            monitor._logger = FakeAgentLogger('fake_agent_logger')

        # We're finally ready start all threads and assert correct behavior.
        # Wait for MonitorsManager to poll for user-agent fragments 10x
        # Since 2 monitors are being polled for fragments, num polls should reach 2 x 10 = 20.
        # However, the monitors always returned a non-changing frag so the callback should be invoked only once.
        # (Note: FakeClock ensures all the above happen within a split second)
        test_manager.start_manager()
        self.assertTrue(fragment_polls.poll_until_target(20, 1))
        self.assertEquals(counter['callback_invocations'], 1)

        # Rerun the above test but this time have monitors return changing fragments.
        # This will cause the user agent callback to be invoked during each round of polling.
        # (The manager polls monitors 10x, and each poll results in a callback invocation).
        fragment_polls = FragmentPolls()
        counter['callback_invocations'] = 0

        def mock_get_user_agent_fragment_2():
            fragment_polls.increment()
            return test_frag + str(fragment_polls.count())

        # patched_monitor_0.get_user_agent_fragment = mock_get_user_agent_fragment_2
        for mon in [patched_monitor_0, patched_monitor_1]:
            mon.get_user_agent_fragment = mock_get_user_agent_fragment_2

        variable_frag_pattern = re.compile(test_frag + r'\d+')

        def augment_user_agent_2(fragments):
            counter['callback_invocations'] += 1
            self.assertIsNotNone(variable_frag_pattern.match(fragments[0]))
        test_manager.set_user_agent_augment_callback(augment_user_agent_2)

        self.assertTrue(fragment_polls.poll_until_target(20, 5))
        self.assertEquals(counter['callback_invocations'], 10)

        test_manager.stop_manager(wait_on_join=False)
        fake_clock.advance_time(increment_by=poll_interval)

    def __create_test_instance(self, config_monitors, platform_monitors, extra_toplevel_config=None):
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, 'agentConfig.json')
        config_fragments_dir = os.path.join(config_dir, 'configs.d')
        os.makedirs(config_fragments_dir)

        monitors_json_array = JsonArray()

        for entry in config_monitors:
            monitors_json_array.add(JsonObject(content=entry))

        fp = open(config_file, 'w')
        toplevel_config = {
            'api_key': 'fake',
            'monitors': monitors_json_array
        }
        if extra_toplevel_config:
            toplevel_config.update(extra_toplevel_config)
        fp.write(json_lib.serialize(JsonObject(**toplevel_config)))
        fp.close()

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        config = Configuration(config_file, default_paths)
        config.parse()
        # noinspection PyTypeChecker
        return MonitorsManager(config, FakePlatform(platform_monitors))


class FakePlatform(object):
    """Fake implementation of PlatformController.

    Only implements the one method required for testing MonitorsManager.
    """
    def __init__(self, default_monitors):
        self.__monitors = default_monitors

    def get_default_monitors(self, _):
        return self.__monitors
