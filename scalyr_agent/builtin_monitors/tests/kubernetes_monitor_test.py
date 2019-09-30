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


import mock
from mock import patch
import threading
import time

from scalyr_agent.builtin_monitors.kubernetes_monitor import KubernetesMonitor, ControlledCacheWarmer
from scalyr_agent.monitor_utils.k8s import K8sApiTemporaryError, K8sApiPermanentError
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent.util import FakeClock, FakeClockCounter
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_util import ScalyrTestUtils
from scalyr_agent.tests.copying_manager_test import FakeMonitor
from scalyr_agent.monitor_utils.tests.k8s_test import FakeCache, FakeK8s


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
            self._KubernetesMonitor__metrics_controlled_warmer = None

        with mock.patch.object(KubernetesMonitor, '_initialize', fake_init):

            manager_poll_interval = 30
            fake_clock = FakeClock()
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        'module': "scalyr_agent.builtin_monitors.kubernetes_monitor",
                    }
                ],
                extra_toplevel_config={
                    'user_agent_refresh_interval': manager_poll_interval,
                },
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

            container_runtime = 'cri'
            @patch.object(k8s_mon, 'get_user_agent_fragment')
            @patch.object(k8s_mon, '_KubernetesMonitor__get_k8s_cache')  # return Mock obj instead of a KubernetesCache)
            def start_test(m2, m1):
                m1.side_effect = fake_get_user_agent_fragment
                m2.return_value.get_api_server_version.side_effect = fake_get_api_server_version
                m2.return_value.get_container_runtime.side_effect = lambda: container_runtime
                manager.set_user_agent_augment_callback(augment_user_agent)

                manager.start_manager()
                fragment_polls.sleep_until_count_or_maxwait(40, manager_poll_interval, maxwait=1)

                m1.assert_called()
                m2.assert_called()
                self.assertEqual(fragment_polls.count(), 40)
                self.assertEqual(counter['callback_invocations'], 3)
                self.assertEquals(detected_fragment_changes, [
                    'k8s=true;k8s-runtime=%s' % container_runtime,
                    'k8s=%s;k8s-runtime=%s' % (version1, container_runtime),
                    'k8s=%s;k8s-runtime=%s' % (version2, container_runtime),
                ])

                manager.stop_manager(wait_on_join=False)
                fake_clock.advance_time(increment_by=manager_poll_interval)
            start_test()

class ControlledCacheWarmerTest(ScalyrTestCase):
    CONTAINER_1 = 'container_1'
    NAMESPACE_1 = 'namespace_1'
    POD_1 = 'pod_1'

    CONTAINER_2 = 'container_2'
    NAMESPACE_2 = 'namespace_2'
    POD_2 = 'pod_2'

    def setUp(self):
        super(ControlledCacheWarmerTest, self).setUp()
        self.__fake_cache = FakeCache()
        self.__warmer_test_instance = ControlledCacheWarmer(max_failure_count=5, blacklist_time_secs=300)
        self.assertFalse(self.__warmer_test_instance.is_running())
        # noinspection PyTypeChecker
        self.__warmer_test_instance.set_k8s_cache(self.__fake_cache)
        self.__warmer_test_instance.start()
        self.assertTrue(self.__warmer_test_instance.is_running())
        self.timeout = 5

    def tearDown(self):
        self.__warmer_test_instance.stop(wait_on_join=False)
        self.__fake_cache.stop()
        self.assertFalse(self.__warmer_test_instance.is_running())

    def test_basic_case(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        fake_cache.wait_until_request_pending()
        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1])

        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1])

        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, success=True)

        warmer.block_until_idle( self.timeout )

        self.assertEqual(warmer.warming_containers(), [])

        self.assertTrue(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

    def test_already_warm(self):
        # Test case where a pod was put into the warming list, but when it is returned by `pick_next_pod`, it is
        # already warmed in the cache.
        # This is a difficult one to test, so we do a little trickery.  We first have the thread that is invoking
        # `pick_next_pod` get tied up blocking for a request for another pod.  That gives us time to manipulate the
        # the caching state for another pod (i.e., get it added to the warming list but then put it into cache before
        # it is returned by `pick_next_pod`)

        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        # Only add in one container so that the ControlledCacheWarmer thread is blocked on getting it.
        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1])

        # Guarantee that the thread is blocked.
        fake_cache.wait_until_request_pending()

        # Now introduce the other pod.
        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.mark_to_warm(self.CONTAINER_2, self.NAMESPACE_2, self.POD_2)
        warmer.end_marking()

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2])
        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1, self.CONTAINER_2])

        # Simulate adding the second one to the cache.  This will trigger it to be `already_warm`
        fake_cache.simulate_add_pod_to_cache(self.NAMESPACE_2, self.POD_2)

        # Ok, now let the ControlledCacheWarmer thread go and try to process everything.
        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, success=True)

        warmer.block_until_idle(self.timeout)

        stats = warmer.get_report_stats()

        success_count = stats.get('success', (0, 0))
        already_warm_count = stats.get('already_warm', (0, 0))

        self.assertEqual(success_count[0], 1)
        self.assertEqual(already_warm_count[0], 1)

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2])
        self.assertEqual(warmer.warming_containers(), [])
        self.assertEqual(warmer.blacklisted_containers(), [])
        self.assertTrue(warmer.is_warm(self.NAMESPACE_1, self.POD_1))
        self.assertTrue(warmer.is_warm(self.NAMESPACE_2, self.POD_2))

    def test_already_warm_two(self):
        # Second case type of already_warmed.  This occurs when the pod is found in cache the second time you
        # try to mark it as active.
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        warmer.begin_marking()
        fake_cache.simulate_add_pod_to_cache(self.NAMESPACE_1, self.POD_1)
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        stats = warmer.get_report_stats()
        success_count = stats.get('success', (1, 1))
        already_warm_count = stats.get('already_warm', (0, 0))

        self.assertEqual(success_count[0], 0)
        self.assertEqual(already_warm_count[0], 1)

    def test_remove_inactive(self):
        warmer = self.__warmer_test_instance

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])

        warmer.begin_marking()
        warmer.end_marking()

        self.assertEqual(warmer.active_containers(), [])

    def test_multiple_pods(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.mark_to_warm(self.CONTAINER_2, self.NAMESPACE_2, self.POD_2)
        warmer.end_marking()

        pod_namespace, _ = fake_cache.wait_until_request_pending()
        if pod_namespace == self.NAMESPACE_1:
            # We have two containers and we don't know which will be warmed first by the abstraction.. so we
            # just handle the two different cases, switching off of the actual request that is pending in the
            # abstraction.  request_a is the first one that has been requested and request_b is the other container.
            request_a_pod_namespace = self.NAMESPACE_1
            request_a_pod_name = self.POD_1
            request_b_pod_namespace = self.NAMESPACE_2
            request_b_pod_name = self.POD_2
            request_b_container = self.CONTAINER_2
        else:
            request_a_pod_namespace = self.NAMESPACE_2
            request_a_pod_name = self.POD_2
            request_b_pod_namespace = self.NAMESPACE_1
            request_b_pod_name = self.POD_1
            request_b_container = self.CONTAINER_1

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2])
        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1, self.CONTAINER_2])

        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))
        self.assertFalse(warmer.is_warm(self.NAMESPACE_2, self.POD_2))

        fake_cache.set_response(request_a_pod_namespace, request_a_pod_name, success=True)
        fake_cache.wait_until_request_pending(namespace=request_b_pod_namespace, name=request_b_pod_name)
        pod_namespace, _ = fake_cache.wait_until_request_pending()
        self.assertEqual(pod_namespace, request_b_pod_namespace)
        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2])
        self.assertEqual(warmer.warming_containers(), [request_b_container])

        self.assertTrue(warmer.is_warm(request_a_pod_namespace, request_a_pod_name))
        self.assertFalse(warmer.is_warm(request_b_pod_namespace, request_b_pod_name))

        fake_cache.set_response(request_b_pod_namespace, request_b_pod_name, success=True)
        warmer.block_until_idle( self.timeout )

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2])
        self.assertEqual(warmer.warming_containers(), [])

        self.assertTrue(warmer.is_warm(request_a_pod_namespace, request_a_pod_name))
        self.assertTrue(warmer.is_warm(request_b_pod_namespace, request_b_pod_name))

    def test_permanent_error(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        fake_cache.wait_until_request_pending()

        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, permanent_error=True)

        warmer.block_until_idle( self.timeout )

        stats = warmer.get_report_stats()
        success_count = stats.get( 'success', (1, 1) )
        perm_error_count = stats.get( 'perm_error', (0, 0) )

        self.assertEqual( success_count[0], 0 )
        self.assertEqual( perm_error_count[0], 1 )

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [])
        self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

    def test_temporary_error(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        for i in range(0, 4):
            fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
            fake_cache.wait_until_request_finished(self.NAMESPACE_1, self.POD_1)

        fake_cache.wait_until_request_pending()

        stats = warmer.get_report_stats()
        success_count = stats.get( 'success', (1, 1) )
        temp_error_count = stats.get( 'temp_error', (0, 0) )

        self.assertEqual( success_count[0], 0 )
        self.assertEqual( temp_error_count[0], 4 )

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(),  [self.CONTAINER_1])
        self.assertEqual(warmer.blacklisted_containers(), [])
        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
        warmer.block_until_idle( self.timeout )

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [])
        self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

        stats = warmer.get_report_stats()
        temp_error_count = stats.get( 'temp_error', (0, 0) )
        self.assertEqual( temp_error_count[0], 5 )

    def test_retry_from_blacklist(self):
        fake_time = 5

        def fake_get_current_time(_):
            return fake_time

        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        with mock.patch.object(ControlledCacheWarmer, '_get_current_time', fake_get_current_time):

            warmer.begin_marking()
            warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
            warmer.end_marking()

            # Have to have 5 temporary errors before it is blacklisted.
            for i in range(0, 4):
                fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
                fake_cache.wait_until_request_finished(self.NAMESPACE_1, self.POD_1)

            fake_cache.wait_until_request_pending()
            fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
            warmer.block_until_idle( self.timeout )

            self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
            self.assertEqual(warmer.warming_containers(), [])
            self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
            self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

            # Now wait at lest 300 seconds to see it come off from the blacklist.
            fake_time += 400

            # Items are only removed from the blacklist during calls to `end_marking`, so we need to do that here.
            warmer.begin_marking()
            warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
            warmer.end_marking()

            self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
            self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1])
            self.assertEqual(warmer.blacklisted_containers(), [])
            self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

            # To test that the entry was properly reset to error count = 0, see if it gets blacklisted after
            # 5 new temporary errors.
            for i in range(0, 4):
                fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
                fake_cache.wait_until_request_finished(self.NAMESPACE_1, self.POD_1)

            fake_cache.wait_until_request_pending()
            fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
            warmer.block_until_idle( self.timeout )

            self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
            self.assertEqual(warmer.warming_containers(), [])
            self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
            self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))


class TestExtraServerAttributes(ScalyrTestCase):

    def _create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        logs_json_array = JsonArray()
        for entry in configuration_logs_entry:
            logs_json_array.add(JsonObject(content=entry))

        config = ScalyrTestUtils.create_configuration(extra_toplevel_config={'logs': logs_json_array})

        self.__monitor_fake_instances = []
        for monitor_log_config in monitors_log_configs:
            self.__monitor_fake_instances.append(FakeMonitor(monitor_log_config))

        # noinspection PyTypeChecker
        return CopyingManager(config, self.__monitor_fake_instances)

    def test_no_extra_server_attributes(self):
        copying_manager = self._create_test_instance([], [])
        attribs = copying_manager._CopyingManager__expanded_server_attributes
        self.assertIsNone(attribs.get('_k8s_ver', none_if_missing=True))

    def test_extra_server_attributes(self):

        def fake_init(self):
            # Initialize variables that would have been
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_ignore = []
            self._KubernetesMonitor__include_controller_info = None
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None

        @mock.patch.object(KubernetesMonitor, '_initialize', fake_init)
        def run_test():
            manager_poll_interval = 30
            fake_clock = FakeClock()
            monitors_manager, config = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        'module': "scalyr_agent.builtin_monitors.kubernetes_monitor",
                    }
                ],
                extra_toplevel_config={'user_agent_refresh_interval': manager_poll_interval},
                null_logger=True,
                fake_clock=fake_clock,
            )
            copying_manager = CopyingManager(config, monitors_manager.monitors)
            self.assertEquals(copying_manager._CopyingManager__expanded_server_attributes.get('_k8s_ver'), 'star')
        run_test()

