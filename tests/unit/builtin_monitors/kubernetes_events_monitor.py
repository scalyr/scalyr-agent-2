# Copyright 2023 Scalyr Inc.
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

from __future__ import unicode_literals
from __future__ import absolute_import

import mock

from scalyr_agent.builtin_monitors.kubernetes_events_monitor import (
    KubernetesEventsMonitor,
    EVENT_OBJECT_FILTER_DEFAULTS,
)
from scalyr_agent.test_base import ScalyrTestCase


class KuberenetesEventsMonitorTestCase(ScalyrTestCase):
    @mock.patch("scalyr_agent.monitor_utils.k8s.K8sNamespaceFilter", mock.Mock())
    def test_is_leader_skip_leader_election_off_default(self):
        monitor_config = {
            "module": "kubernetes_events_monitor",
            "event_object_filter": EVENT_OBJECT_FILTER_DEFAULTS,
        }
        global_config = mock.Mock()
        global_config.log_rotation_max_bytes = 1024
        global_config.log_rotation_backup_count = 2
        mock_logger = mock.Mock()

        monitor = KubernetesEventsMonitor(
            monitor_config, mock_logger, global_config=global_config
        )
        monitor._pod_name = "pod1"

        monitor._get_current_leader = mock.Mock(return_value="pod2")
        self.assertEqual(monitor._get_current_leader.call_count, 0)
        self.assertFalse(monitor._is_leader(mock.Mock()))
        self.assertEqual(monitor._get_current_leader.call_count, 1)

        monitor._get_current_leader = mock.Mock(return_value="pod1")
        self.assertEqual(monitor._get_current_leader.call_count, 0)
        self.assertTrue(monitor._is_leader(mock.Mock()))
        self.assertEqual(monitor._get_current_leader.call_count, 1)

    @mock.patch("scalyr_agent.monitor_utils.k8s.K8sNamespaceFilter", mock.Mock())
    def test_is_leader_skip_leader_election_on_default(self):
        monitor_config = {
            "module": "kubernetes_events_monitor",
            "event_object_filter": EVENT_OBJECT_FILTER_DEFAULTS,
            "skip_leader_election": True,
        }
        global_config = mock.Mock()
        global_config.log_rotation_max_bytes = 1024
        global_config.log_rotation_backup_count = 2
        mock_logger = mock.Mock()

        monitor = KubernetesEventsMonitor(
            monitor_config, mock_logger, global_config=global_config
        )
        monitor._pod_name = "pod1"

        # when this config is set to True, is_leader() should always immediately return True
        monitor._get_current_leader = mock.Mock(return_value="pod2")
        self.assertEqual(monitor._get_current_leader.call_count, 0)
        self.assertTrue(monitor._is_leader(mock.Mock()))
        self.assertEqual(monitor._get_current_leader.call_count, 0)

        monitor._get_current_leader = mock.Mock(return_value="pod1")
        self.assertEqual(monitor._get_current_leader.call_count, 0)
        self.assertTrue(monitor._is_leader(mock.Mock()))
        self.assertEqual(monitor._get_current_leader.call_count, 0)
