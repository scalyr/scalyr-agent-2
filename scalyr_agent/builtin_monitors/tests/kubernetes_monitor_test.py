# Copyright 2019 Scalyr Inc.
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
# author: Edward Chee <echee@scalyr.com>


__author__ = 'echee@scalyr.com'


from collections import Counter

import mock
from mock import patch

from scalyr_agent.builtin_monitors.kubernetes_monitor import KubernetesMonitor
from scalyr_agent.util import FakeClock, FakeClockCounter
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils


class KubernetesMonitorTest(ScalyrTestCase):
    """Exercises various different user-agent fragments returned by KubernetesMonitor.
    Also captures the situation where the monitor is polled before the k8s cache has obtained a version,
    in which case it must a version string indicating presence of k8s but no actual version.

    Implemntation:  A MonitorsManager and KubernetesMonitor is started.  The docker api lib is completely mocked out.
    The _initialize() method is also replaced with a fake method that simply initializes empty variables
    to enable the main loop to run.
    """

    @patch('scalyr_agent.builtin_monitors.kubernetes_monitor.docker')
    def test_user_agent_fragment(self, mock_docker):

        def fake_init(self):
            # Initialize variables that would have been
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_ignore = []
            self._KubernetesMonitor__include_controller_info = None
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None

        with mock.patch.object(KubernetesMonitor, '_initialize', fake_init):

            manager_poll_interval = 30
            fake_clock = FakeClock()
            manager = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        'module': "scalyr_agent.builtin_monitors.kubernetes_monitor",
                    }
                ],
                extra_toplevel_config={'user_agent_refresh_interval': manager_poll_interval},
                null_logger=True,
                fake_clock=fake_clock,
            )

            fragment_polls = FakeClockCounter(fake_clock, num_waiters=2)
            counter = Counter()
            detected_fragment_changes = []

            # Mock the callback (that would normally be invoked on ScalyrClientSession
            def augment_user_agent(fragments):
                counter['callback_invocations'] += 1
                detected_fragment_changes.append(fragments[0])

            # Decorate the get_user_agent_fragment() function as follows:
            # Each invocation increments the FakeClockCounter
            # Simulate the following race condition:
            # 1. The first 10 polls by MonitorsManager is such that KubernetesMonitor has not yet started. Therefore,
            #     the version is None
            # 2. After the 20th poll, version is set
            # 3. After the 30th poll, version changes (does not normally happen, but we ensure this repeated check)
            #
            # Total number of times the user_agent_callback is called should be twice:
            # - once for when docker version is None (fragment is 'k8s=true')
            # - once for when docker version changes to a real number
            version1 = '1.13.4'
            version2 = '1.14.1'
            k8s_mon = manager.monitors[0]
            original_get_user_agent_fragment = k8s_mon.get_user_agent_fragment

            def fake_get_user_agent_fragment():
                result = original_get_user_agent_fragment()
                fragment_polls.increment()
                return result

            def fake_get_api_server_version():
                if fragment_polls.count() < 10:
                    return None
                elif fragment_polls.count() < 20:
                    return version1
                else:
                    return version2

            with patch.object(
                k8s_mon, 'get_user_agent_fragment'
            ) as m1, patch.object(
                k8s_mon, '_KubernetesMonitor__get_k8s_cache'  # return Mock obj instead of a KubernetesCache
            ) as m2:
                m1.side_effect = fake_get_user_agent_fragment
                m2.return_value.get_api_server_version.side_effect = fake_get_api_server_version
                manager.set_user_agent_augment_callback(augment_user_agent)

                manager.start_manager()
                fragment_polls.sleep_until_count_or_maxwait(40, manager_poll_interval, maxwait=1)

                m1.assert_called()
                m2.assert_called()
                self.assertEqual(fragment_polls.count(), 40)
                self.assertEqual(counter['callback_invocations'], 3)
                self.assertEquals(detected_fragment_changes, [
                    'k8s=true',
                    'k8s=%s' % version1,
                    'k8s=%s' % version2,
                ])

                manager.stop_manager(wait_on_join=False)
                fake_clock.advance_time(increment_by=manager_poll_interval)
