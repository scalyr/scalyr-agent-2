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

from __future__ import unicode_literals
from __future__ import absolute_import

import re
import time
import warnings
import platform
from string import Template
from collections import OrderedDict

import sys

from requests.packages.urllib3.exceptions import InsecureRequestWarning
from six import StringIO

from scalyr_agent import AgentLogger
from scalyr_agent.monitor_utils.k8s import (
    KubeletApi,
    KubeletApiException,
    K8sConfigBuilder,
    K8sNamespaceFilter,
    PodInfo,
)

__author__ = "echee@scalyr.com"


from scalyr_agent.builtin_monitors.kubernetes_monitor import (
    KubernetesMonitor,
    ControlledCacheWarmer,
    ContainerChecker,
    _ignore_old_dead_container,
    construct_metrics_container_name,
)
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.util import FakeClock, FakeClockCounter
from scalyr_agent.test_base import ScalyrTestCase, BaseScalyrLogCaptureTestCase
from scalyr_agent.test_util import ScalyrTestUtils

from tests.unit.monitor_utils.k8s_test import FakeCache
from tests.unit.configuration_test import TestConfigurationBase
from tests.unit.copying_manager_tests.copying_manager_test import FakeMonitor
from scalyr_agent.test_base import skipIf

import mock
from mock import patch
from six.moves import range


class KubernetesMonitorTest(ScalyrTestCase):
    """Exercises various different user-agent fragments returned by KubernetesMonitor.
    Also captures the situation where the monitor is polled before the k8s cache has obtained a version,
    in which case it must a version string indicating presence of k8s but no actual version.

    Implemntation:  A MonitorsManager and KubernetesMonitor is started.  The docker api lib is completely mocked out.
    The _initialize() method is also replaced with a fake method that simply initializes empty variables
    to enable the main loop to run.
    """

    @patch("scalyr_agent.builtin_monitors.kubernetes_monitor.docker")
    def test_user_agent_fragment(self, mock_docker):
        def fake_init(self):
            # Initialize variables that would have been
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_include = (
                K8sNamespaceFilter.default_value()
            )
            self._KubernetesMonitor__include_controller_info = None
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None
            self._KubernetesMonitor__metrics_controlled_warmer = None

        with mock.patch.object(KubernetesMonitor, "_initialize", fake_init):

            manager_poll_interval = 30
            fake_clock = FakeClock()
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {"module": "scalyr_agent.builtin_monitors.kubernetes_monitor"}
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                },
                null_logger=True,
                fake_clock=fake_clock,
            )

            fragment_polls = FakeClockCounter(fake_clock, num_waiters=2)
            counter = {"callback_invocations": 0}
            detected_fragment_changes = []

            # Mock the callback (that would normally be invoked on ScalyrClientSession
            def augment_user_agent(fragments):
                counter["callback_invocations"] += 1
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
            version1 = "1.13.4"
            version2 = "1.14.1"
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

            container_runtime = "cri"

            @patch.object(k8s_mon, "get_user_agent_fragment")
            @patch.object(
                k8s_mon, "_KubernetesMonitor__get_k8s_cache"
            )  # return Mock obj instead of a KubernetesCache)
            def start_test(m2, m1):
                m1.side_effect = fake_get_user_agent_fragment
                m2.return_value.get_api_server_version.side_effect = (
                    fake_get_api_server_version
                )
                m2.return_value.get_container_runtime.side_effect = (
                    lambda: container_runtime
                )
                manager.set_user_agent_augment_callback(augment_user_agent)

                manager.start_manager()
                fragment_polls.sleep_until_count_or_maxwait(
                    40, manager_poll_interval, maxwait=1
                )

                m1.assert_called()
                m2.assert_called()
                self.assertEqual(fragment_polls.count(), 40)
                self.assertEqual(counter["callback_invocations"], 3)
                self.assertEquals(
                    detected_fragment_changes,
                    [
                        "k8s=true;k8s-runtime=%s" % container_runtime,
                        "k8s=%s;k8s-runtime=%s" % (version1, container_runtime),
                        "k8s=%s;k8s-runtime=%s" % (version2, container_runtime),
                    ],
                )

                manager.stop_manager(wait_on_join=False)
                fake_clock.advance_time(increment_by=manager_poll_interval)

            start_test()  # pylint: disable=no-value-for-parameter


class ControlledCacheWarmerTest(ScalyrTestCase):
    CONTAINER_1 = "container_1"
    NAMESPACE_1 = "namespace_1"
    POD_1 = "pod_1"

    CONTAINER_2 = "container_2"
    NAMESPACE_2 = "namespace_2"
    POD_2 = "pod_2"

    def setUp(self):
        super(ControlledCacheWarmerTest, self).setUp()
        self.__fake_cache = FakeCache()
        self.__warmer_test_instance = ControlledCacheWarmer(
            max_failure_count=5, blacklist_time_secs=300
        )
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

        warmer.block_until_idle(self.timeout)

        self.assertEqual(warmer.warming_containers(), [])

        self.assertTrue(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

    def test_has_been_used(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        # containers that haven't been added should never be pending_first_use
        self.assertFalse(warmer.pending_first_use(self.CONTAINER_1))

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        # warming entry is pending first use as soon as it has been created (happens in mark to warm if not exists)
        self.assertTrue(warmer.pending_first_use(self.CONTAINER_1))
        warmer.end_marking()

        fake_cache.wait_until_request_pending()
        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, success=True)

        warmer.block_until_idle(self.timeout)
        # pod is warm, but warming entry is still pending first use until marked
        self.assertTrue(warmer.is_warm(self.NAMESPACE_1, self.POD_1))
        self.assertTrue(warmer.pending_first_use(self.CONTAINER_1))

        warmer.mark_has_been_used(self.CONTAINER_1)
        self.assertFalse(warmer.pending_first_use(self.CONTAINER_1))
        self.assertTrue(self.CONTAINER_1 in warmer.active_containers())

    def test_has_been_used_unmark_to_warm(self):
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        # containers that haven't been added should never be pending_first_use
        self.assertFalse(warmer.pending_first_use(self.CONTAINER_1))

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        # warming entry is pending first use as soon as it has been created (happens in mark to warm if not exists)
        self.assertTrue(warmer.pending_first_use(self.CONTAINER_1))
        warmer.end_marking()

        fake_cache.wait_until_request_pending()
        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, success=True)

        warmer.block_until_idle(self.timeout)

        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        self.assertTrue(warmer.pending_first_use(self.CONTAINER_1))
        warmer.mark_has_been_used(self.CONTAINER_1, unmark_to_warm=True)
        warmer.end_marking()

        self.assertFalse(warmer.pending_first_use(self.CONTAINER_1))
        self.assertFalse(self.CONTAINER_1 in warmer.active_containers())

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

        self.assertEqual(
            warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )
        self.assertEqual(
            warmer.warming_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )

        # Simulate adding the second one to the cache.  This will trigger it to be `already_warm`
        fake_cache.simulate_add_pod_to_cache(self.NAMESPACE_2, self.POD_2)

        # Ok, now let the ControlledCacheWarmer thread go and try to process everything.
        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, success=True)

        warmer.block_until_idle(self.timeout)

        stats = warmer.get_report_stats()

        success_count = stats.get("success", (0, 0))
        already_warm_count = stats.get("already_warm", (0, 0))

        self.assertEqual(success_count[0], 1)
        self.assertEqual(already_warm_count[0], 1)

        self.assertEqual(
            warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )
        self.assertEqual(warmer.warming_containers(), [])
        self.assertEqual(warmer.blacklisted_containers(), [])
        self.assertTrue(warmer.is_warm(self.NAMESPACE_1, self.POD_1))
        self.assertTrue(warmer.is_warm(self.NAMESPACE_2, self.POD_2))

    def test_already_warm_two(self):
        # Second case type of already_warmed.  This occurs when the pod is found in cache the second time you
        # try to mark it as active.
        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        # Stop the warmer thread since we don't need it for the test, and to avoid a race condition that sometimes
        # results in finding too many "already_warm" results
        warmer.stop()

        warmer.begin_marking()
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        warmer.begin_marking()
        fake_cache.simulate_add_pod_to_cache(self.NAMESPACE_1, self.POD_1)
        warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
        warmer.end_marking()

        stats = warmer.get_report_stats()
        success_count = stats.get("success", (1, 1))
        already_warm_count = stats.get("already_warm", (0, 0))

        self.assertEqual(success_count[0], 0)
        self.assertEqual(already_warm_count[0], 1)

    def test_remove_inactive(self):
        warmer = self.__warmer_test_instance

        # Stop the warmer thread since we don't need it for the test
        warmer.stop()

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

        self.assertEqual(
            warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )
        self.assertEqual(
            warmer.warming_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )

        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))
        self.assertFalse(warmer.is_warm(self.NAMESPACE_2, self.POD_2))

        fake_cache.set_response(
            request_a_pod_namespace, request_a_pod_name, success=True
        )
        fake_cache.wait_until_request_pending(
            namespace=request_b_pod_namespace, name=request_b_pod_name
        )
        pod_namespace, _ = fake_cache.wait_until_request_pending()
        self.assertEqual(pod_namespace, request_b_pod_namespace)
        self.assertEqual(
            warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )
        self.assertEqual(warmer.warming_containers(), [request_b_container])

        self.assertTrue(warmer.is_warm(request_a_pod_namespace, request_a_pod_name))
        self.assertFalse(warmer.is_warm(request_b_pod_namespace, request_b_pod_name))

        fake_cache.set_response(
            request_b_pod_namespace, request_b_pod_name, success=True
        )
        warmer.block_until_idle(self.timeout)

        self.assertEqual(
            warmer.active_containers(), [self.CONTAINER_1, self.CONTAINER_2]
        )
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

        warmer.block_until_idle(self.timeout)

        stats = warmer.get_report_stats()
        success_count = stats.get("success", (1, 1))
        perm_error_count = stats.get("perm_error", (0, 0))

        self.assertEqual(success_count[0], 0)
        self.assertEqual(perm_error_count[0], 1)

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
        success_count = stats.get("success", (1, 1))
        temp_error_count = stats.get("temp_error", (0, 0))

        self.assertEqual(success_count[0], 0)
        self.assertEqual(temp_error_count[0], 4)

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.blacklisted_containers(), [])
        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

        fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
        warmer.block_until_idle(self.timeout)

        self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
        self.assertEqual(warmer.warming_containers(), [])
        self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
        self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))

        stats = warmer.get_report_stats()
        temp_error_count = stats.get("temp_error", (0, 0))
        self.assertEqual(temp_error_count[0], 5)

    def test_retry_from_blacklist(self):
        fake_time = 5

        def fake_get_current_time(_):
            return fake_time

        warmer = self.__warmer_test_instance
        fake_cache = self.__fake_cache

        with mock.patch.object(
            ControlledCacheWarmer, "_get_current_time", fake_get_current_time
        ):

            warmer.begin_marking()
            warmer.mark_to_warm(self.CONTAINER_1, self.NAMESPACE_1, self.POD_1)
            warmer.end_marking()

            # Have to have 5 temporary errors before it is blacklisted.
            for i in range(0, 4):
                fake_cache.set_response(
                    self.NAMESPACE_1, self.POD_1, temporary_error=True
                )
                fake_cache.wait_until_request_finished(self.NAMESPACE_1, self.POD_1)

            fake_cache.wait_until_request_pending()
            fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
            warmer.block_until_idle(self.timeout)

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
                fake_cache.set_response(
                    self.NAMESPACE_1, self.POD_1, temporary_error=True
                )
                fake_cache.wait_until_request_finished(self.NAMESPACE_1, self.POD_1)

            fake_cache.wait_until_request_pending()
            fake_cache.set_response(self.NAMESPACE_1, self.POD_1, temporary_error=True)
            warmer.block_until_idle(self.timeout)

            self.assertEqual(warmer.active_containers(), [self.CONTAINER_1])
            self.assertEqual(warmer.warming_containers(), [])
            self.assertEqual(warmer.blacklisted_containers(), [self.CONTAINER_1])
            self.assertFalse(warmer.is_warm(self.NAMESPACE_1, self.POD_1))


class TestExtraServerAttributes(ScalyrTestCase):
    def _create_test_instance(self, configuration_logs_entry, monitors_log_configs):
        logs_json_array = []
        for entry in configuration_logs_entry:
            logs_json_array.append(entry)

        config = ScalyrTestUtils.create_configuration(
            extra_toplevel_config={"logs": logs_json_array}
        )

        self.__monitor_fake_instances = []
        for monitor_log_config in monitors_log_configs:
            self.__monitor_fake_instances.append(FakeMonitor(monitor_log_config))

        # noinspection PyTypeChecker
        return CopyingManager(config, self.__monitor_fake_instances)

    def test_no_extra_server_attributes(self):
        copying_manager = self._create_test_instance([], [])
        attribs = copying_manager._CopyingManager__expanded_server_attributes
        self.assertIsNone(attribs.get("_k8s_ver", None))

    def test_extra_server_attributes(self):
        def fake_init(self):
            # Initialize variables that would have been
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_include = (
                K8sNamespaceFilter.default_value()
            )
            self._KubernetesMonitor__include_controller_info = None
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None

        @mock.patch.object(KubernetesMonitor, "_initialize", fake_init)
        def run_test():
            manager_poll_interval = 30
            fake_clock = FakeClock()
            monitors_manager, config = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {"module": "scalyr_agent.builtin_monitors.kubernetes_monitor"}
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            copying_manager = CopyingManager(config, monitors_manager.monitors)
            self.assertEquals(
                copying_manager._CopyingManager__expanded_server_attributes.get(
                    "_k8s_ver"
                ),
                "star",
            )

        run_test()


class FakeKubernetesApi:
    def __init__(self):
        self.token = "FakeToken"


class FakeResponse:
    def __init__(self, text="{}"):
        self.status_code = 200
        self.text = text


class TestKubeletApi(BaseScalyrLogCaptureTestCase):
    def test_basic_case(self):
        def fake_get(self, url, verify):
            resp = FakeResponse()
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            api = KubeletApi(
                FakeKubernetesApi(), host_ip="127.0.0.1", node_name="FakeNode"
            )
            result = api.query_stats()
            self.assertEqual(result, {})

    @skipIf(platform.system() == "Windows", "Skipping Linux only tests on Windows")
    def test_unverified_https(self):
        def fake_get(self, url, verify):
            resp = FakeResponse()
            warnings.warn(
                (
                    "Unverified HTTPS request is being made. "
                    "Adding certificate verification is strongly advised. See: "
                    "https://urllib3.readthedocs.io/en/latest/advanced-usage.html"
                    "#ssl-warnings"
                ),
                InsecureRequestWarning,
            )
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            new_out, new_err = StringIO(), StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            try:
                sys.stdout, sys.stderr = new_out, new_err
                api = KubeletApi(
                    FakeKubernetesApi(),
                    host_ip="127.0.0.1",
                    node_name="FakeNode",
                    kubelet_url_template=Template("https://${host_ip}"),
                    verify_https=False,
                )
                result = api.query_stats()
                self.assertEqual(result, {})
                self.assertLogFileContainsLineRegex(
                    r".*WARNING \[core\] \[k8s.py:\d+\] Accessing Kubelet with an unverified HTTPS request\."
                )
                self.assertFalse(new_err.getvalue())
                self.assertFalse(new_out.getvalue())
            finally:
                sys.stdout, sys.stderr = old_out, old_err

    def test_unverified_http(self):
        def fake_get(self, url, verify):
            resp = FakeResponse()
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            new_out, new_err = StringIO(), StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            try:
                sys.stdout, sys.stderr = new_out, new_err
                api = KubeletApi(
                    FakeKubernetesApi(),
                    host_ip="127.0.0.1",
                    node_name="FakeNode",
                    kubelet_url_template=Template("http://${host_ip}"),
                    verify_https=False,
                )
                result = api.query_stats()
                self.assertEqual(result, {})
                self.assertLogFileDoesntContainsLineRegex(
                    ".*"
                    + re.escape(
                        "WARNING [core] [k8s.py:2215] Accessing Kubelet with an unverified HTTPS request."
                    )
                )
                self.assertFalse(new_err.getvalue())
                self.assertFalse(new_out.getvalue())
            finally:
                sys.stdout, sys.stderr = old_out, old_err

    @mock.patch("scalyr_agent.monitor_utils.k8s.global_log")
    def test_error_response(self, mock_global_log):
        def fake_get(self, url, verify):
            resp = FakeResponse()
            resp.status_code = 404
            resp.text = "foo bar error"
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            api = KubeletApi(
                FakeKubernetesApi(),
                host_ip="127.0.0.1",
                node_name="FakeNode",
            )

            self.assertEqual(mock_global_log.error.call_count, 0)
            expected_msg = (
                r"Invalid response from Kubelet API when querying '/stats/summary' "
                r"\(https://127.0.0.1:10250/stats/summary\): foo bar error"
            )
            self.assertRaisesRegexp(KubeletApiException, expected_msg, api.query_stats)

            expected_msg = (
                "Invalid response while querying the Kubelet API on "
                "https://127.0.0.1:10250/stats/summary"
            )
            self.assertEqual(mock_global_log.error.call_count, 1)
            self.assertTrue(
                expected_msg in mock_global_log.error.call_args_list[0][0][0]
            )

    @mock.patch("scalyr_agent.monitor_utils.k8s.global_log")
    def test_fallback(self, mock_global_log):
        self._fake_get_called = False

        def fake_get(self2, url, verify):
            resp = FakeResponse()
            if not self._fake_get_called:
                resp.status_code = 403
                self._fake_get_called = True
            else:
                resp.status_code = 200
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            api = KubeletApi(
                FakeKubernetesApi(),
                host_ip="127.0.0.1",
                node_name="FakeNode",
            )

            self.assertEqual(mock_global_log.warn.call_count, 0)
            result = api.query_stats()
            self.assertEqual(result, {})

            expected_msg = (
                "Invalid response while querying the Kubelet API on "
                "https://127.0.0.1:10250/stats/summary. Falling back to older endpoint "
                "(http://127.0.0.1:10255)."
            )

            self.assertEqual(mock_global_log.warn.call_count, 1)
            self.assertTrue(
                expected_msg in mock_global_log.warn.call_args_list[0][0][0]
            )

    def test_host_ip_format(self):
        def fake_get(self2, url, verify):
            resp = FakeResponse()
            self.assertEqual(url, "http://127.0.0.1/stats/summary")
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            api = KubeletApi(
                FakeKubernetesApi(),
                host_ip="127.0.0.1",
                node_name="FakeNode",
                kubelet_url_template=Template("http://${host_ip}"),
            )
            result = api.query_stats()
            self.assertEqual(result, {})

    def test_node_name_format(self):
        def fake_get(self2, url, verify):
            resp = FakeResponse()
            self.assertEqual(url, "http://FakeNode/stats/summary")
            return resp

        with mock.patch.object(KubeletApi, "_get", fake_get):
            api = KubeletApi(
                FakeKubernetesApi(),
                host_ip="127.0.0.1",
                node_name="FakeNode",
                kubelet_url_template=Template("http://${node_name}"),
            )
            result = api.query_stats()
            self.assertEqual(result, {})

    def test_ignore_old_dead_container(self):
        now = time.time()

        container = {"State": "stopped", "Created": now}
        created_before = now - 5
        result = _ignore_old_dead_container(container, created_before)
        self.assertFalse(result)

        container = {"State": "stopped", "Created": now - 5}
        created_before = now
        result = _ignore_old_dead_container(container, created_before)
        self.assertTrue(result)

        # Only non-running containers should be filtered
        container = {"State": "running", "Created": now - 5}
        created_before = now
        result = _ignore_old_dead_container(container, created_before)
        self.assertFalse(result)

        # created_before is None
        container = {"State": "stopped", "Created": now - 5}
        created_before = None
        result = _ignore_old_dead_container(container, created_before)
        self.assertFalse(result)


class ContainerCheckerTest(TestConfigurationBase):
    def setUp(self):
        super(ContainerCheckerTest, self).setUp()
        self.k8s_info = {
            "pod_name": "test_pod",
            "pod_namespace": "test_namespace",
            "k8s_container_name": "xxx_test_container",
        }

    def test_variable_container_log_config(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            k8s_logs: [
              {
                "k8s_container_glob": "no_match",
                "test": "no_match",
              },
              {
                "attributes": { "zzz_templ_container_name": "${k8s_container_name}" }
              }
            ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        cc = ContainerChecker(
            config={"k8s_use_v2_attributes": True},
            global_config=config,
            logger=mock.Mock(),
            socket_file=None,
            docker_api_version=None,
            agent_pod=None,
            host_hostname=None,
            log_path=None,
            include_all=True,
            include_controller_info=True,
            namespaces_to_include=[K8sNamespaceFilter.default_value()],
            ignore_pod_sandboxes=False,
        )
        cc._ContainerChecker__k8s_config_builder = K8sConfigBuilder(
            config.k8s_log_configs,
            mock.Mock(),
            True,
        )
        cc.get_cluster_name = lambda *_: "the-cluster-name"

        def _pod(pod_namespace, pod_name, **kwargs):
            return mock.MagicMock(
                name=pod_name,
                namespace=pod_namespace,
                node_name="asd",
                uid="lkjsefr",
                labels={},
                controller=None,
                annotations={},
                container_names=["one", "two"],
            )

        result = cc._ContainerChecker__get_log_config_for_container(
            "12345",
            info={
                "name": "myname",
                "k8s_info": self.k8s_info,
                "log_path": "/var/log/test.log",
            },
            k8s_cache=mock.Mock(pod=_pod),
            base_attributes=cc._ContainerChecker__get_base_attributes(),
        )
        assert "zzz_templ_container_name" in result["attributes"]
        assert "xxx_test_container" == result["attributes"]["zzz_templ_container_name"]

    def test_pod_info_digest(self):
        pod_info_1 = PodInfo(
            name="loggen-58c5486566-fdmzf",
            namespace="default",
            uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
            node_name="test-node",
            labels={"a": 1, "b": 2, "c": 3},
            container_names=["a", "b", "c", "d"],
            annotations={"a": 1, "b": 2, "c": 3},
            controller=None,
        )

        pod_info_2 = PodInfo(
            name="loggen-58c5486566-fdmzf",
            namespace="default",
            uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
            node_name="test-node",
            labels={"b": 2, "c": 3, "a": 1},
            container_names=["a", "c", "b", "d"],
            annotations={"b": 2, "c": 3, "a": 1},
            controller=None,
        )

        pod_info_3 = PodInfo(
            name="loggen-58c5486566-fdmzf",
            namespace="default",
            uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
            node_name="test-node",
            labels=OrderedDict([("c", 3), ("b", 2), ("a", 1)]),
            container_names=["a", "b", "c", "d"],
            annotations=OrderedDict([("c", 3), ("b", 2), ("a", 1)]),
            controller=None,
        )

        pod_info_4 = PodInfo(
            name="loggen-58c5486566-fdmzf",
            namespace="default",
            uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
            node_name="test-node",
            labels=OrderedDict([("c", 3), ("b", 2), ("a", 5)]),
            container_names=["a", "b", "c", "d"],
            annotations=OrderedDict([("c", 3), ("b", 2), ("a", 1)]),
            controller=None,
        )

        # Ensure that the digest is the same even if the dict item order is not the same
        # (dict item ordering is not guaranteed)
        self.assertEqual(pod_info_1.digest, pod_info_2.digest)
        self.assertEqual(pod_info_1.digest, pod_info_3.digest)
        self.assertEqual(pod_info_2.digest, pod_info_3.digest)

        self.assertTrue(pod_info_1.digest != pod_info_4.digest)
        self.assertTrue(pod_info_2.digest != pod_info_4.digest)
        self.assertTrue(pod_info_3.digest != pod_info_4.digest)


class KubernetesContainerMetricsTest(ScalyrTestCase):
    @mock.patch("scalyr_agent.builtin_monitors.kubernetes_monitor.docker")
    def test_cri_metrics(self, mock_docker):
        fake_pod_info = PodInfo(
            name="loggen-58c5486566-fdmzf",
            namespace="default",
            uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
            node_name="test-node",
            labels={},
            container_names=["random-logger"],
            annotations={},
            controller=None,
        )

        fake_containers = {
            "container1": {
                "k8s_info": {
                    "k8s_container_name": "random-logger",
                    "pod_info": fake_pod_info,
                    "pod_name": "loggen-58c5486566-fdmzf",
                    "pod_namespace": "default",
                    "pod_uid": "5ef12d19-d8e5-4280-9cdf-a80bae251c68",
                },
                "log_path": "/var/log/containers/test.log",
                "name": "random-logger",
                "metrics_name": construct_metrics_container_name(
                    "random-logger",
                    "loggen-58c5486566-fdmzf",
                    "default",
                    "5ef12d19-d8e5-4280-9cdf-a80bae251c68",
                ),
            }
        }

        fake_stats_response = '{"node": {"fs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 10243129344, "time": "2021-03-05T03:57:28Z", "inodes": 3907584, "inodesUsed": 141939}, "network": {"name": "eth0", "rxErrors": 0, "interfaces": [{"txErrors": 0, "txBytes": 0, "rxBytes": 0, "name": "tunl0", "rxErrors": 0}, {"txErrors": 0, "txBytes": 12767090, "rxBytes": 3843488321, "name": "eth0", "rxErrors": 0}, {"txErrors": 0, "txBytes": 0, "rxBytes": 1108, "name": "cni0", "rxErrors": 0}, {"txErrors": 0, "txBytes": 0, "rxBytes": 0, "name": "ip6tnl0", "rxErrors": 0}], "txErrors": 0, "txBytes": 12767090, "rxBytes": 3843488321, "time": "2021-03-05T03:57:28Z"}, "systemContainers": [{"memory": {"pageFaults": 318879, "rssBytes": 41275392, "majorPageFaults": 8019, "workingSetBytes": 64704512, "time": "2021-03-05T03:57:27Z", "usageBytes": 92921856}, "name": "kubelet", "startTime": "2021-03-05T03:38:07Z", "cpu": {"usageCoreNanoSeconds": 0, "usageNanoCores": 0, "time": "2021-03-05T03:57:27Z"}}, {"memory": {"pageFaults": 0, "rssBytes": 317759488, "majorPageFaults": 0, "workingSetBytes": 409108480, "availableBytes": 1677070336, "time": "2021-03-05T03:57:28Z", "usageBytes": 539336704}, "name": "pods", "startTime": "2021-03-05T03:55:04Z", "cpu": {"usageCoreNanoSeconds": 271826164990, "usageNanoCores": 244034553, "time": "2021-03-05T03:57:28Z"}}], "rlimit": {"maxpid": 4194304, "curproc": 1026, "time": "2021-03-05T03:57:30Z"}, "startTime": "2021-03-03T17:54:00Z", "memory": {"pageFaults": 37092, "rssBytes": 481333248, "majorPageFaults": 33, "workingSetBytes": 626536448, "availableBytes": 1459642368, "time": "2021-03-05T03:57:28Z", "usageBytes": 1598562304}, "runtime": {"imageFs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 1708203927, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 62096}}, "cpu": {"usageCoreNanoSeconds": 750131721656, "usageNanoCores": 317926037, "time": "2021-03-05T03:57:28Z"}, "nodeName": "minikube"}, "pods": [{"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 69632, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 9}, "podRef": {"namespace": "default", "name": "loggen-58c5486566-fdmzf", "uid": "5ef12d19-d8e5-4280-9cdf-a80bae251c68"}, "volume": [{"name": "default-token-nm2ks", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:48:07Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:47:08Z", "memory": {"pageFaults": 0, "rssBytes": 602112, "majorPageFaults": 0, "workingSetBytes": 2662400, "time": "2021-03-05T03:57:28Z", "usageBytes": 2764800}, "cpu": {"usageCoreNanoSeconds": 1433157151, "usageNanoCores": 1649262, "time": "2021-03-05T03:57:28Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 45056, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "random-logger", "startTime": "2021-03-05T03:47:12Z", "memory": {"pageFaults": 90156, "rssBytes": 331776, "majorPageFaults": 0, "workingSetBytes": 2080768, "time": "2021-03-05T03:57:20Z", "usageBytes": 2183168}, "cpu": {"usageCoreNanoSeconds": 1378023167, "usageNanoCores": 2202002, "time": "2021-03-05T03:57:20Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 24576, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 7}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 84214, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 28}, "podRef": {"namespace": "kube-system", "name": "kindnet-kblsz", "uid": "95313449-857e-4a23-a4c6-653ff6cd2583"}, "volume": [{"name": "kindnet-token-njbbz", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:39:07Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:26Z", "memory": {"pageFaults": 0, "rssBytes": 4919296, "majorPageFaults": 0, "workingSetBytes": 11616256, "availableBytes": 40812544, "time": "2021-03-05T03:57:22Z", "usageBytes": 17784832}, "cpu": {"usageCoreNanoSeconds": 1152746538, "usageNanoCores": 181623, "time": "2021-03-05T03:57:22Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 16384, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "kindnet-cni", "startTime": "2021-03-05T03:38:28Z", "memory": {"pageFaults": 17754, "rssBytes": 4919296, "majorPageFaults": 1056, "workingSetBytes": 11309056, "availableBytes": 41119744, "time": "2021-03-05T03:57:30Z", "usageBytes": 17453056}, "cpu": {"usageCoreNanoSeconds": 1096529102, "usageNanoCores": 221068, "time": "2021-03-05T03:57:30Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 67830, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 26}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 4483135, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 303}, "podRef": {"namespace": "scalyr", "name": "scalyr-agent-2-dxclt", "uid": "f5433cb8-3cac-46cf-b6ec-4e599c9a0342"}, "volume": [{"name": "scalyr-service-account-token-8fwkf", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:57:06Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:56:35Z", "memory": {"pageFaults": 0, "rssBytes": 28041216, "majorPageFaults": 0, "workingSetBytes": 40833024, "availableBytes": 483454976, "time": "2021-03-05T03:57:17Z", "usageBytes": 64294912}, "cpu": {"usageCoreNanoSeconds": 1551418749, "usageNanoCores": 21544383, "time": "2021-03-05T03:57:17Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 8192, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "scalyr-agent", "startTime": "2021-03-05T03:56:35Z", "memory": {"pageFaults": 20526, "rssBytes": 28041216, "majorPageFaults": 99, "workingSetBytes": 40341504, "availableBytes": 483946496, "time": "2021-03-05T03:57:19Z", "usageBytes": 63422464}, "cpu": {"usageCoreNanoSeconds": 1571428372, "usageNanoCores": 21552013, "time": "2021-03-05T03:57:19Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 4474943, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 301}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 57344, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 17}, "podRef": {"namespace": "kube-system", "name": "storage-provisioner", "uid": "e81c9a9c-7c77-4fe5-9f94-41136b8f6b62"}, "volume": [{"name": "storage-provisioner-token-j6wwb", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:39:07Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:26Z", "memory": {"pageFaults": 0, "rssBytes": 7356416, "majorPageFaults": 0, "workingSetBytes": 11939840, "time": "2021-03-05T03:57:27Z", "usageBytes": 18669568}, "cpu": {"usageCoreNanoSeconds": 4580373461, "usageNanoCores": 3189595, "time": "2021-03-05T03:57:27Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 12288, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 3}, "name": "storage-provisioner", "startTime": "2021-03-05T03:38:59Z", "memory": {"pageFaults": 10989, "rssBytes": 7200768, "majorPageFaults": 1584, "workingSetBytes": 11636736, "time": "2021-03-05T03:57:18Z", "usageBytes": 18345984}, "cpu": {"usageCoreNanoSeconds": 4397854608, "usageNanoCores": 3607819, "time": "2021-03-05T03:57:18Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 45056, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 14}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 65536, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 21}, "podRef": {"namespace": "kube-system", "name": "coredns-74ff55c5b-2v4jg", "uid": "4eafdee9-c8fc-4183-b36c-a6005e087764"}, "volume": [{"name": "config-volume", "inodesFree": 3813595, "capacityBytes": 62725623808, "availableBytes": 43075002368, "usedBytes": 12288, "time": "2021-03-05T03:39:07Z", "inodes": 3907584, "inodesUsed": 5}, {"name": "coredns-token-6jq4k", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:39:07Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:39:00Z", "memory": {"pageFaults": 0, "rssBytes": 8196096, "majorPageFaults": 0, "workingSetBytes": 13176832, "availableBytes": 165081088, "time": "2021-03-05T03:57:22Z", "usageBytes": 27475968}, "cpu": {"usageCoreNanoSeconds": 8895284967, "usageNanoCores": 10009731, "time": "2021-03-05T03:57:22Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 8192, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "coredns", "startTime": "2021-03-05T03:39:00Z", "memory": {"pageFaults": 12507, "rssBytes": 8196096, "majorPageFaults": 1947, "workingSetBytes": 12955648, "availableBytes": 165302272, "time": "2021-03-05T03:57:28Z", "usageBytes": 27254784}, "cpu": {"usageCoreNanoSeconds": 8847112503, "usageNanoCores": 10696843, "time": "2021-03-05T03:57:28Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 45056, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 14}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 122880, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 18}, "podRef": {"namespace": "kube-system", "name": "kube-apiserver-minikube", "uid": "c767dbeb9ddd2d01964c2fc02c621c4e"}, "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 0, "rssBytes": 183521280, "majorPageFaults": 0, "workingSetBytes": 205963264, "time": "2021-03-05T03:57:27Z", "usageBytes": 234110976}, "cpu": {"usageCoreNanoSeconds": 153365786247, "usageNanoCores": 141945504, "time": "2021-03-05T03:57:27Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 69632, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "kube-apiserver", "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 271755, "rssBytes": 183476224, "majorPageFaults": 83226, "workingSetBytes": 205443072, "time": "2021-03-05T03:57:29Z", "usageBytes": 233590784}, "cpu": {"usageCoreNanoSeconds": 153521115898, "usageNanoCores": 136248870, "time": "2021-03-05T03:57:29Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 53248, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 16}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 155648, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 25}, "podRef": {"namespace": "kube-system", "name": "kube-controller-manager-minikube", "uid": "57b8c22dbe6410e4bd36cf14b0f8bdc7"}, "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 0, "rssBytes": 41242624, "majorPageFaults": 0, "workingSetBytes": 55177216, "time": "2021-03-05T03:57:23Z", "usageBytes": 80031744}, "cpu": {"usageCoreNanoSeconds": 55004270907, "usageNanoCores": 50623011, "time": "2021-03-05T03:57:23Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 77824, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "kube-controller-manager", "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 31284, "rssBytes": 41193472, "majorPageFaults": 5676, "workingSetBytes": 54882304, "time": "2021-03-05T03:57:21Z", "usageBytes": 79736832}, "cpu": {"usageCoreNanoSeconds": 54883234484, "usageNanoCores": 51592924, "time": "2021-03-05T03:57:21Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 77824, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 23}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 28672, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 9}, "podRef": {"namespace": "kube-system", "name": "kube-scheduler-minikube", "uid": "6b4a0ee8b3d15a1c2e47c15d32e6eb0d"}, "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 0, "rssBytes": 12656640, "majorPageFaults": 0, "workingSetBytes": 21057536, "time": "2021-03-05T03:57:13Z", "usageBytes": 32837632}, "cpu": {"usageCoreNanoSeconds": 7393175515, "usageNanoCores": 5479576, "time": "2021-03-05T03:57:13Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 16384, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "kube-scheduler", "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 18282, "rssBytes": 12656640, "majorPageFaults": 4125, "workingSetBytes": 20799488, "time": "2021-03-05T03:57:25Z", "usageBytes": 32579584}, "cpu": {"usageCoreNanoSeconds": 7415797084, "usageNanoCores": 5160641, "time": "2021-03-05T03:57:25Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 12288, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 7}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 73728, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 13}, "podRef": {"namespace": "kube-system", "name": "etcd-minikube", "uid": "c31fe6a5afdd142cf3450ac972274b36"}, "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 0, "rssBytes": 20578304, "majorPageFaults": 0, "workingSetBytes": 29360128, "time": "2021-03-05T03:57:21Z", "usageBytes": 36302848}, "cpu": {"usageCoreNanoSeconds": 36074754936, "usageNanoCores": 27064651, "time": "2021-03-05T03:57:21Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 40960, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "etcd", "startTime": "2021-03-05T03:38:00Z", "memory": {"pageFaults": 21120, "rssBytes": 20525056, "majorPageFaults": 4323, "workingSetBytes": 29003776, "time": "2021-03-05T03:57:22Z", "usageBytes": 35909632}, "cpu": {"usageCoreNanoSeconds": 36054608288, "usageNanoCores": 26153936, "time": "2021-03-05T03:57:22Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 32768, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 11}}]}, {"ephemeral-storage": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 88310, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 34}, "podRef": {"namespace": "kube-system", "name": "kube-proxy-7vvhk", "uid": "2cc3cd45-5765-4cdd-9bc5-528501ef9274"}, "volume": [{"name": "kube-proxy", "inodesFree": 3813595, "capacityBytes": 62725623808, "availableBytes": 43075002368, "usedBytes": 16384, "time": "2021-03-05T03:39:07Z", "inodes": 3907584, "inodesUsed": 7}, {"name": "kube-proxy-token-tvmsd", "inodesFree": 254651, "capacityBytes": 1043087360, "availableBytes": 1043075072, "usedBytes": 12288, "time": "2021-03-05T03:39:07Z", "inodes": 254660, "inodesUsed": 9}], "process_stats": {"process_count": 0}, "startTime": "2021-03-05T03:38:26Z", "memory": {"pageFaults": 0, "rssBytes": 10645504, "majorPageFaults": 0, "workingSetBytes": 17891328, "time": "2021-03-05T03:57:22Z", "usageBytes": 25665536}, "cpu": {"usageCoreNanoSeconds": 1464616252, "usageNanoCores": 240928, "time": "2021-03-05T03:57:22Z"}, "containers": [{"logs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 8192, "time": "2021-03-05T03:57:30Z", "inodes": 3907584, "inodesUsed": 2}, "name": "kube-proxy", "startTime": "2021-03-05T03:38:27Z", "memory": {"pageFaults": 23067, "rssBytes": 10641408, "majorPageFaults": 1782, "workingSetBytes": 17551360, "time": "2021-03-05T03:57:20Z", "usageBytes": 25288704}, "cpu": {"usageCoreNanoSeconds": 1437692295, "usageNanoCores": 232273, "time": "2021-03-05T03:57:20Z"}, "rootfs": {"inodesFree": 3765645, "capacityBytes": 62725623808, "availableBytes": 49265778688, "usedBytes": 63734, "time": "2021-03-05T03:57:27Z", "inodes": 3907584, "inodesUsed": 25}}]}]}'

        def fake_init(self):
            # Initialize variables that would have been
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_include = (
                K8sNamespaceFilter.default_value()
            )
            self._KubernetesMonitor__include_controller_info = True
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None
            self._KubernetesMonitor__metrics_controlled_warmer = None

        def fake_get(self, url, verify):
            resp = FakeResponse(text=fake_stats_response)
            return resp

        self.emit_results = []

        def fake_emit(
            this,
            metric_name,
            metric_value,
            extra_fields=None,
            monitor=None,
            monitor_id_override=None,
        ):
            result = {
                "metric_name": metric_name,
                "metric_value": metric_value,
                "extra_fields": extra_fields,
                "monitor": monitor,
                "monitor_id_override": monitor_id_override,
            }
            self.emit_results.append(result)

        with mock.patch.object(KubernetesMonitor, "_initialize", fake_init):
            with mock.patch.object(AgentLogger, "emit_value", fake_emit):
                manager_poll_interval = 30
                fake_clock = FakeClock()
                monitors_manager, config = ScalyrTestUtils.create_test_monitors_manager(
                    config_monitors=[
                        {"module": "scalyr_agent.builtin_monitors.kubernetes_monitor"}
                    ],
                    extra_toplevel_config={
                        "user_agent_refresh_interval": manager_poll_interval
                    },
                    null_logger=True,
                    fake_clock=fake_clock,
                )
                k8s_mon = monitors_manager.monitors[0]

                with mock.patch.object(KubeletApi, "_get", fake_get):
                    api = KubeletApi(
                        FakeKubernetesApi(), host_ip="127.0.0.1", node_name="FakeNode"
                    )
                    k8s_mon._KubernetesMonitor__gather_metrics_from_kubelet(
                        fake_containers, api, "TestCluster"
                    )

        self.emit_results = sorted(self.emit_results, key=lambda k: k["metric_name"])

        self.assertEqual(
            self.emit_results[0],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.cpu.total_usage",
                "metric_value": 1378023167,
                "monitor": None,
            },
        )
        self.assertEqual(
            self.emit_results[1],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.mem.stat.total_pgfault",
                "metric_value": 90156,
                "monitor": None,
            },
        )
        self.assertEqual(
            self.emit_results[2],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.mem.stat.total_pgmajfault",
                "metric_value": 0,
                "monitor": None,
            },
        )
        self.assertEqual(
            self.emit_results[3],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.mem.stat.total_rss",
                "metric_value": 331776,
                "monitor": None,
            },
        )
        self.assertEqual(
            self.emit_results[4],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.mem.usage",
                "metric_value": 2183168,
                "monitor": None,
            },
        )
        self.assertEqual(
            self.emit_results[5],
            {
                "monitor_id_override": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                "extra_fields": {
                    "pod_uid": "k8s_random-logger_loggen-58c5486566-fdmzf_default_5ef12d19-d8e5-4280-9cdf-a80bae251c68_0",
                    "k8s-cluster": "TestCluster",
                    "k8s-controller": "none",
                },
                "metric_name": "docker.mem.workingSetBytes",
                "metric_value": 2080768,
                "monitor": None,
            },
        )
