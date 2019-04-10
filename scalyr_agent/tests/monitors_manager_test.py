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


import re

from collections import Counter

import scalyr_agent.util as scalyr_util

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils
from scalyr_agent.util import FakeClockCounter


class MonitorsManagerTest(ScalyrTestCase):
    def test_single_module(self):
        test_manager = ScalyrTestUtils.create_test_monitors_manager([
            {
                'module': 'scalyr_agent.builtin_monitors.test_monitor',
                'gauss_mean': 0
            }
        ], [])
        self.assertEquals(len(test_manager.monitors), 1)
        self.assertEquals(test_manager.monitors[0].monitor_name, 'test_monitor()')

    def test_multiple_modules(self):
        test_manager = ScalyrTestUtils.create_test_monitors_manager([
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
        test_manager = ScalyrTestUtils.create_test_monitors_manager([
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
        # Fake the clock to fast-forward MonitorsManager sleep loop
        fake_clock = scalyr_util.FakeClock()
        test_manager = ScalyrTestUtils.create_test_monitors_manager(
            config_monitors=[
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
            ],
            platform_monitors=[],
            extra_toplevel_config={'user_agent_refresh_interval': poll_interval},
            null_logger=True,
            fake_clock=fake_clock,
        )
        self.assertEquals(test_manager._user_agent_refresh_interval, 30)  # ensure config setting works
        self.assertEquals(len(test_manager.monitors), 3)
        patched_monitor_0 = test_manager.monitors[0]
        patched_monitor_1 = test_manager.monitors[1]
        unpatched_monitor = test_manager.monitors[2]

        # The MonitorsManager + 3 monitor threads will wait on the fake clock
        fragment_polls = FakeClockCounter(fake_clock, num_waiters=4)

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

        # We're finally ready start all threads and assert correct behavior.
        # Wait for MonitorsManager to poll for user-agent fragments 10x
        # Since 2 monitors are being polled for fragments, num polls should reach 2 x 10 = 20.
        # However, the monitors always return a non-changing frag, so the callback should be invoked only once.
        # (Note: FakeClock ensures all the above happen within a split second)
        test_manager.start_manager()
        self.assertTrue(fragment_polls.sleep_until_count_or_maxwait(20, poll_interval, 1))
        self.assertEquals(counter['callback_invocations'], 1)

        # Rerun the above test but this time have monitors return changing fragments.
        # This will cause the user agent callback to be invoked during each round of polling.
        # (The manager polls monitors 10x, and each poll results in a callback invocation).
        fragment_polls = FakeClockCounter(fake_clock, num_waiters=4)
        counter['callback_invocations'] = 0

        def mock_get_user_agent_fragment_2():
            fragment_polls.increment()
            return test_frag + str(fragment_polls.count())

        for mon in [patched_monitor_0, patched_monitor_1]:
            mon.get_user_agent_fragment = mock_get_user_agent_fragment_2

        variable_frag_pattern = re.compile(test_frag + r'\d+')

        def augment_user_agent_2(fragments):
            counter['callback_invocations'] += 1
            self.assertIsNotNone(variable_frag_pattern.match(fragments[0]))
        test_manager.set_user_agent_augment_callback(augment_user_agent_2)

        self.assertTrue(fragment_polls.sleep_until_count_or_maxwait(20, poll_interval, 1))
        self.assertEquals(counter['callback_invocations'], 10)

        # set_daemon=True obviates the following (saves a few seconds in cleanup):
        test_manager.stop_manager(wait_on_join=False)
        fake_clock.advance_time(increment_by=poll_interval)
