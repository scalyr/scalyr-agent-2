# Copyright 2017 Scalyr Inc.
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
# author: Saurabh Jain <saurabh@scalyr.com>

__author__ = 'saurabh@scalyr.com'

from collections import defaultdict
from scalyr_agent.builtin_monitors.linux_process_metrics import ProcessMonitor, Metric, ProcessList
from scalyr_agent.test_base import ScalyrTestCase
import scalyr_agent.scalyr_logging as scalyr_logging


class TestProcessMonitorInitialize(ScalyrTestCase):
    def setUp(self):
        self.config_commandline = {
            "module": "scalyr_agent.builtin_monitors.linux_process_metrics",
            "id": "myapp",
            "commandline": ".foo.*",
        }

    def test_initialize_monitor(self):
        monitor = ProcessMonitor(self.config_commandline, scalyr_logging.getLogger("syslog_monitor[test]"))
        self.assertEqual(monitor._ProcessMonitor__metrics_history, defaultdict(dict))
        self.assertEqual(monitor._ProcessMonitor__aggregated_metrics, {})


class TestProcessMonitorRecordMetrics(ScalyrTestCase):
    """
    Tests the record_metrics method of ProcessMonitor class
    """

    def setUp(self):
        self.config_commandline = {
            "module": "scalyr_agent.builtin_monitors.linux_process_metrics",
            "id": "myapp",
            "commandline": ".foo.*",
        }

        self.monitor = ProcessMonitor(self.config_commandline, scalyr_logging.getLogger("syslog_monitor[test]"))

    def test_empty_metrics(self):
        self.monitor.record_metrics(666, {})
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, defaultdict(dict))

    def test_single_process_single_epoch(self):
        metric = Metric('fakemetric', 'faketype')
        metrics = {
            metric: 21
        }
        self.monitor.record_metrics(555, metrics)
        expected_history = {
            555: {metric: [21]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

    def test_single_process_multiple_epochs(self):
        metric = Metric('fakemetric', 'faketype')

        # epoch 1
        self.monitor.record_metrics(777, {metric: 1.2})
        expected_history = {
            777: {metric: [1.2]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

        # epoch 2
        self.monitor.record_metrics(777, {metric: 1.9})
        expected_history = {
            777: {metric: [1.2, 1.9]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

    def test_multi_process_single_epoch(self):
        metric1 = Metric('fakemetric1', 'faketype1')
        metric2 = Metric('fakemetric2', 'faketype2')

        self.monitor.record_metrics(111, {metric1: 1.2})
        self.monitor.record_metrics(222, {metric2: 2.87})
        expected_history = {
            111: {metric1: [1.2]},
            222: {metric2: [2.87]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

    def test_multi_process_multi_epochs(self):
        metric1 = Metric('fakemetric1', 'faketype1')
        metric2 = Metric('fakemetric2', 'faketype2')

        # epoch 1
        self.monitor.record_metrics(111, {metric1: 1.2})
        self.monitor.record_metrics(222, {metric2: 2.87})
        expected_history = {
            111: {metric1: [1.2]},
            222: {metric2: [2.87]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

        # epoch 2
        self.monitor.record_metrics(111, {metric1: 1.6})
        self.monitor.record_metrics(222, {metric2: 2.92})
        expected_history = {
            111: {metric1: [1.2, 1.6]},
            222: {metric2: [2.87, 2.92]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})


class TestProcessListUtility(ScalyrTestCase):
    def setUp(self):
        self.ps = ProcessList()

    def test_no_process(self):
        # override
        self.ps.parent_to_children_map = defaultdict(list)
        self.ps.processes = []
        
        self.assertEqual(self.ps.get_child_processes('bad pid'), [])
        self.assertEqual(self.ps.get_matches_commandline('.*'), [])
        self.assertEqual(self.ps.get_matches_commandline_with_children('.*'), [])

    def test_single_process_no_children(self):
        # override
        # process id 0 is basically no process. PID 1 is the main process of a terminal
        self.ps.processes = [
            {'pid': 2, 'ppid': 1, 'cmd': 'python hello.py'},
            {'pid': 1, 'ppid': 0, 'cmd': '/bin/bash'}
        ]
        self.ps.parent_to_children_map = defaultdict(list)
        self.ps.parent_to_children_map[1] = [2]
        self.ps.parent_to_children_map[0] = [1]

        self.assertEqual(self.ps.get_child_processes('bad pid'), [])
        self.assertEqual(self.ps.get_child_processes(1), [2])
        # positive match
        self.assertEqual(set(self.ps.get_matches_commandline('.*')), {1, 2})
        self.assertEqual(self.ps.get_matches_commandline('.*bash.*'), [1])
        self.assertEqual(self.ps.get_matches_commandline('.*py.*'), [2])
        self.assertEqual(set(self.ps.get_matches_commandline_with_children('.*')), {1, 2})

    def test_single_process_with_children(self):
        # override
        # process id 0 is basically no process. PID 1 is the main process of a terminal
        self.ps.processes = [
            {'pid': 2, 'ppid': 1, 'cmd': 'python hello.py'},
            {'pid': 3, 'ppid': 2, 'cmd': 'sleep 2'},
            {'pid': 1, 'ppid': 0, 'cmd': '/bin/bash'}
        ]
        self.ps.parent_to_children_map = defaultdict(list)
        self.ps.parent_to_children_map[1] = [2]
        self.ps.parent_to_children_map[2] = [3]
        self.ps.parent_to_children_map[0] = [1]

        self.assertEqual(self.ps.get_child_processes('bad pid'), [])
        self.assertEqual(set(self.ps.get_child_processes(1)), {2, 3})
        self.assertEqual(self.ps.get_child_processes(2), [3])
        # positive match
        self.assertEqual(set(self.ps.get_matches_commandline('.*')), {1, 2, 3})
        self.assertEqual(self.ps.get_matches_commandline('.*bash.*'), [1])
        self.assertEqual(self.ps.get_matches_commandline('.*py.*'), [2])
        self.assertEqual(set(self.ps.get_matches_commandline_with_children('.*')), {1, 2, 3})

    def test_multiple_processes_with_children(self):
        # override
        # process id 0 is basically no process. PID 1 is the main process of a terminal
        self.ps.processes = [
            {'pid': 2, 'ppid': 1, 'cmd': 'python hello.py'},
            {'pid': 3, 'ppid': 2, 'cmd': 'sleep 2'},
            {'pid': 1, 'ppid': 0, 'cmd': '/bin/bash'},
            {'pid': 4, 'ppid': 0, 'cmd': 'sleep 10000'}
        ]
        self.ps.parent_to_children_map = defaultdict(list)
        self.ps.parent_to_children_map[1] = [2]
        self.ps.parent_to_children_map[2] = [3]
        self.ps.parent_to_children_map[0] = [1, 4]

        self.assertEqual(self.ps.get_child_processes('bad pid'), [])
        self.assertEqual(set(self.ps.get_child_processes(1)), {2, 3})
        self.assertEqual(self.ps.get_child_processes(2), [3])
        # positive match
        self.assertEqual(set(self.ps.get_matches_commandline('.*')), {1, 2, 3, 4})
        self.assertEqual(self.ps.get_matches_commandline('.*bash.*'), [1])
        self.assertEqual(self.ps.get_matches_commandline('.*py.*'), [2])
        self.assertEqual(set(self.ps.get_matches_commandline_with_children('.*')), {1, 2, 3, 4})


class TestProcessMonitorRunningTotal(ScalyrTestCase):
    """
    Tests the calculations of the running totals of the metrics.
    """

    def setUp(self):
        self.config_commandline = {
            "module": "scalyr_agent.builtin_monitors.linux_process_metrics",
            "id": "myapp",
            "commandline": ".foo.*",
        }
        self.monitor = ProcessMonitor(self.config_commandline, scalyr_logging.getLogger("syslog_monitor[test]"))

    def test_no_history(self):
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {})

    def test_single_process_single_epoch(self):
        metric = Metric('fakemetric', 'faketype')
        metrics = {
            metric: 21
        }
        self.monitor.record_metrics(555, metrics)
        self.monitor._ProcessMonitor__pids = [555]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            555: {metric: [21]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {metric: 21})

    def test_single_process_multiple_epoch(self):
        metric = Metric('fakemetric', 'faketype')

        # epoch 1
        metrics = {metric: 21}
        self.monitor.record_metrics(555, metrics)
        self.monitor._ProcessMonitor__pids = [555]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {555: {metric: [21]}}
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {metric: 21})

        # epoch 2
        # before epoch 2, the reset is called for absolute metrics
        self.monitor._reset_absolute_metrics()

        metrics = {metric: 21.5}
        self.monitor.record_metrics(555, metrics)
        self.monitor._ProcessMonitor__pids = [555]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {555: {metric: [21, 21.5]}}
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(self.monitor._ProcessMonitor__aggregated_metrics, {metric: 21.5})

    def test_multiple_process_multiple_epochs(self):
        metric1 = Metric('fakemetric1', 'faketype1')
        metric2 = Metric('fakemetric2', 'faketype2')

        # epoch 1
        metrics1 = {metric1: 21}
        metrics2 = {metric2: 100.0}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [21]},
            2: {metric2: [100.0]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: 21,
                metric2: 100.0
            }
        )
        # epoch 2
        # before epoch 2, the reset is called for absolute metrics
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 21.11}
        metrics2 = {metric2: 100.11}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [21, 21.11]},
            2: {metric2: [100.0, 100.11]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: 21.11,
                metric2: 100.11
            }
        )

    def test_multiple_process_multiple_epochs_cumulative_metrics(self):
        metric1 = Metric('app.cpu', 'system')

        # epoch 1
        metrics1 = {metric1: 20}
        metrics2 = {metric1: 40}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [20]},
            2: {metric1: [40]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: 0
            }
        )
        # epoch 2
        # before epoch 2, the reset is called for absolute metrics
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 22}
        metrics2 = {metric1: 44}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [20, 22]},
            2: {metric1: [40, 44]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (22 - 20) + (44 - 40)
            }
        )

        # epoch 3
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 25}
        metrics2 = {metric1: 48}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        # we only keep the last 2 historical values
        expected_history = {
            1: {metric1: [22, 25]},
            2: {metric1: [44, 48]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (22 - 20) + (44 - 40) + (25 - 22) + (48 - 44)
            }
        )

    def test_multiple_process_multiple_epochs_cumulative_metrics_one_process_death(self):
        """
        Same as test_multiple_process_multiple_epochs_cumulative_metrics
        but one process dies after epoch 2
        """

        metric1 = Metric('app.cpu', 'system')

        # epoch 1
        metrics1 = {metric1: 21}
        metrics2 = {metric1: 100.0}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [21]},
            2: {metric1: [100.0]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: 0
            }
        )
        # epoch 2
        # before epoch 2, the reset is called for absolute metrics
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 30.1}
        metrics2 = {metric1: 100.2}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [21, 30.1]},
            2: {metric1: [100.0, 100.2]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (30.1 - 21) + (100.2 - 100.0)
            }
        )

        # epoch 3
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 26.0}
        metrics2 = {metric1: 103}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)

        # Process 1 dies.. boom
        self.monitor._ProcessMonitor__pids = [2]
        self.monitor._calculate_aggregated_metrics()

        # we only keep the last 2 historical values
        expected_history = {
            1: {metric1: [30.1, 26.0]},
            2: {metric1: [100.2, 103]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)

        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (30.1 - 21) + (100.2 - 100.0) + (103 - 100.2)
            }
        )

    def test_multiple_process_multiple_epochs_cumulative_metrics_all_process_death(self):
        """
        Same as test_multiple_process_multiple_epochs_cumulative_metrics_one_process_death
        but all processes die after epoch 2
        """

        metric1 = Metric('app.cpu', 'system')

        # epoch 1
        metrics1 = {metric1: 20}
        metrics2 = {metric1: 40}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1,2 ]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [20]},
            2: {metric1: [40]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: 0
            }
        )
        # epoch 2
        # before epoch 2, the reset is called for absolute metrics
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 25}
        metrics2 = {metric1: 46}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)
        self.monitor._ProcessMonitor__pids = [1, 2]
        self.monitor._calculate_aggregated_metrics()
        expected_history = {
            1: {metric1: [20, 25]},
            2: {metric1: [40, 46]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)
        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (25 - 20) + (46 - 40)
            }
        )

        # epoch 3
        self.monitor._reset_absolute_metrics()

        metrics1 = {metric1: 23}
        metrics2 = {metric1: 43}
        self.monitor.record_metrics(1, metrics1)
        self.monitor.record_metrics(2, metrics2)

        # Process 1 and 2 die.. boom
        # we should ensure the total running value for metric doesn't go down.
        self.monitor._ProcessMonitor__pids = []
        self.monitor._calculate_aggregated_metrics()

        # we only keep the last 2 historical values
        expected_history = {
            1: {metric1: [25, 23]},
            2: {metric1: [46, 43]}
        }
        self.assertEqual(self.monitor._ProcessMonitor__metrics_history, expected_history)

        self.assertEqual(
            self.monitor._ProcessMonitor__aggregated_metrics,
            {
                metric1: (25 - 20) + (46 - 40)
            }
        )
