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


import threading
from collections import Counter

import mock
from mock import patch

from scalyr_agent.builtin_monitors.docker_monitor import DockerMonitor
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils
from scalyr_agent.util import FakeClock, FakeClockCounter


class DockerMonitorTest(ScalyrTestCase):
    """This test exercises various different user-agent fragments returned by DockerMonitor.
    It also captures the situation where the monitor is polled before it has obtained a version, in which case it must
    return a base fragment indicating docker but no version.

    Implemntation:  A MonitorsManager and DockerMonitor is started.  But the docker api lib is completely mocked out.
    The _initialize() method is also mocked with a fake method
    """

    @mock.patch('scalyr_agent.builtin_monitors.docker_monitor.docker')
    def test_user_agent_fragment(self, mocked_docker):

        def fake_init(self):
            """Simulate syslog mode (null container checker). Init the version variable and it's lock"""
            self._DockerMonitor__container_checker = None
            self._DockerMonitor__version_lock = threading.RLock()
            self._DockerMonitor__version = None

        with mock.patch.object(DockerMonitor, '_initialize', fake_init):

            manager_poll_interval = 30
            fake_clock = FakeClock()
            manager = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        'module': "scalyr_agent.builtin_monitors.docker_monitor",
                        'log_mode': "syslog"
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
            # 1. The first 10 polls by MonitorsManager is such that DockerMonitor has not yet started. Therefore,
            #     the docker version is None
            # 2. After the 20th poll, docker version is set
            # 3. After the 30th poll, docker mode changes to docker_api|raw
            # 4. After the 40th poll, docker mode changes to docker_api|api
            #
            # Note: (3) and (4) do not happen in real life.  We force these config changes to test permutations
            # of user agent fragments for different config scenarios
            #
            # Total number of times the user_agent_callback is called should be twice:
            # - once for when docker version is None (fragment is 'docker=true')
            # - once for when docker version changes to a real number
            fake_docker_version = '18.09.2'
            docker_mon = manager.monitors[0]
            original_get_user_agent_fragment = docker_mon.get_user_agent_fragment
            original_monitor_config_get = docker_mon._config.get

            def fake_get_user_agent_fragment():
                result = original_get_user_agent_fragment()
                fragment_polls.increment()
                return result

            def fake_fetch_and_set_version():
                # Simulate slow-to-start DockerMonitor where version is set only after 10th poll by MonitorsManager
                # Thus, polls 0-9 return in version=None which ultimately translates to 'docker=true' fragment
                docker_mon._DockerMonitor__version_lock.acquire()
                try:
                    if fragment_polls.count() < 10:
                        docker_mon._DockerMonitor__version = None
                    else:
                        docker_mon._DockerMonitor__version = fake_docker_version
                finally:
                    docker_mon._DockerMonitor__version_lock.release()

            def fake_monitor_config_get(key):
                # Fake the return values from MonitorConfig.get in order to exercise different permutations of
                # user_agent fragment.
                if key == 'log_mode':
                    if fragment_polls.count() < 20:
                        return 'syslog'
                    else:
                        return 'docker_api'
                elif key == 'docker_raw_logs':
                    if fragment_polls.count() < 30:
                        return True
                    else:
                        return False
                else:
                    return original_monitor_config_get(key)

            with patch.object(
                docker_mon, 'get_user_agent_fragment'
            ) as m1, patch.object(
                docker_mon, '_fetch_and_set_version'
            ) as m2, patch.object(
                docker_mon._config, 'get'
            ) as m3:
                m1.side_effect = fake_get_user_agent_fragment
                m2.side_effect = fake_fetch_and_set_version
                m3.side_effect = fake_monitor_config_get
                manager.set_user_agent_augment_callback(augment_user_agent)

                manager.start_manager()
                fragment_polls.sleep_until_count_or_maxwait(40, manager_poll_interval, maxwait=1)

                m1.assert_called()
                m2.assert_called()
                m3.assert_called()
                self.assertEquals(fragment_polls.count(), 40)
                self.assertEquals(counter['callback_invocations'], 4)
                self.assertEquals(detected_fragment_changes, [
                    'docker=true',
                    'docker=18.09.2|syslog',
                    'docker=18.09.2|docker_api|raw',
                    'docker=18.09.2|docker_api|api',
                ])

                manager.stop_manager(wait_on_join=False)
                fake_clock.advance_time(increment_by=manager_poll_interval)
