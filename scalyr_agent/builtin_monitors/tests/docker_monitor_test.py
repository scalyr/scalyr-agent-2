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


import os
import threading

import mock
from mock import patch
from mock import Mock

import scalyr_agent.util as scalyr_util

from scalyr_agent.builtin_monitors.docker_monitor import DockerMonitor
from scalyr_agent.builtin_monitors.docker_monitor import _get_containers
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

    def parse_file_as_json( self, filename ):
        result = {}
        with open( filename, 'r' ) as f:
            content = f.read()
            result = scalyr_util.json_decode( content )
        return result

    def get_data_filename( self, name ):
        base = os.path.dirname( os.path.realpath( __file__ ) )
        return os.path.join( base, 'data', name )

    def get_mock_docker_client( self, data_file ):
        filename = self.get_data_filename( data_file )
        data = self.parse_file_as_json( filename )
        client = Mock()
        client.containers.return_value = data
        return client

    def test_get_containers_no_include_no_exclude( self ):
        """ Test get containers when no glob filters are applied """

        expected_ids = [
            "87d533137e70601d17a4bf9d563b11d528ba81e31e2299eb8d4ab2ef5a54f0c0",
            "84afc8ee4d726544e77dcfe22c6f5be04f36b115ea99c0510d612666f83da1ce",
            "e511aaf76add81d41c1536b2a93a17448d9f9d3c6a3f8a5abab1d9a582c397fc",
            "cfcb7f7d1481c805f91fd6c8c120300a586978fa2541a58026bd930eeeda3e36",
            "b8757266fd6a9efcb40a2881215d8d3642e6f8a0cfdcbb941382d002f31dcca4",
            "343c05b55c1b0cebca6df0309a4892974c5ed3013731433461ffe7442223659a",
            "58ded582ebf14063bff3b15cd3962035be9904b73318796f1119d71472801d23",
            "c4eacccbf687f408c708b12fa875ab55f4d6d0aad8e2eec489ba9712e041bd14",
        ]

        client = self.get_mock_docker_client( 'containers-running.json' )
        containers = _get_containers( client )

        self.assertEqual( len(expected_ids), len(containers) )

        for cid in expected_ids:
            self.assertTrue( cid in containers )

    def test_get_containers_include_no_exclude( self ):
        """ Test get_containers when an include filter but no exclude filter is applied """
        expected_ids = [
            "e511aaf76add81d41c1536b2a93a17448d9f9d3c6a3f8a5abab1d9a582c397fc",
            "cfcb7f7d1481c805f91fd6c8c120300a586978fa2541a58026bd930eeeda3e36",
            "58ded582ebf14063bff3b15cd3962035be9904b73318796f1119d71472801d23",
            "c4eacccbf687f408c708b12fa875ab55f4d6d0aad8e2eec489ba9712e041bd14",
        ]

        glob_list = {
            'include': ['*include1*', '*include2*']
        }

        client = self.get_mock_docker_client( 'containers-running.json' )
        containers = _get_containers( client, glob_list=glob_list )

        self.assertEqual( len(expected_ids), len(containers) )

        for cid in expected_ids:
            self.assertTrue( cid in containers )

    def test_get_containers_no_include_exclude( self ):
        """ Test get_containers when no include filter is applied but an exclude filter is"""
        expected_ids = [
            "87d533137e70601d17a4bf9d563b11d528ba81e31e2299eb8d4ab2ef5a54f0c0",
            "84afc8ee4d726544e77dcfe22c6f5be04f36b115ea99c0510d612666f83da1ce",
            "b8757266fd6a9efcb40a2881215d8d3642e6f8a0cfdcbb941382d002f31dcca4",
            "343c05b55c1b0cebca6df0309a4892974c5ed3013731433461ffe7442223659a",
            "58ded582ebf14063bff3b15cd3962035be9904b73318796f1119d71472801d23",
            "c4eacccbf687f408c708b12fa875ab55f4d6d0aad8e2eec489ba9712e041bd14",
        ]

        glob_list = {
            'exclude': ['*include1-exclude*', '*include2-exclude*']
        }

        client = self.get_mock_docker_client( 'containers-running.json' )
        containers = _get_containers( client, glob_list=glob_list )

        self.assertEqual( len(expected_ids), len(containers) )

        for cid in expected_ids:
            self.assertTrue( cid in containers )

    def test_get_containers_include_exclude( self ):
        """ Test get_containers when both an include and an exclude filter are applied"""
        expected_ids = [
            "b8757266fd6a9efcb40a2881215d8d3642e6f8a0cfdcbb941382d002f31dcca4",
            "343c05b55c1b0cebca6df0309a4892974c5ed3013731433461ffe7442223659a",
            "58ded582ebf14063bff3b15cd3962035be9904b73318796f1119d71472801d23",
            "c4eacccbf687f408c708b12fa875ab55f4d6d0aad8e2eec489ba9712e041bd14",
        ]

        glob_list = {
            'include': ['*include*'],
            'exclude': ['*exclude*']
        }

        client = self.get_mock_docker_client( 'containers-running.json' )
        containers = _get_containers( client, glob_list=glob_list )
        self.assertEqual( len(expected_ids), len(containers) )

        for cid in expected_ids:
            self.assertTrue( cid in containers )

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
            counter = {'callback_invocations': 0}
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

            @patch.object(docker_mon, 'get_user_agent_fragment')
            @patch.object(docker_mon, '_fetch_and_set_version')
            @patch.object(docker_mon._config, 'get')
            def start_test(m3, m2, m1):
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
            start_test()

