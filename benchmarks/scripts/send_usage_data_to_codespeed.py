#!/usr/bin/env python
# Copyright 2014-2020 Scalyr Inc.
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

"""
Script which utilizes ProcessTracker abstraction from Scalyr Linux Process Metrics monitor to
collect various agent metrics which are used to track agent resource utilization over time.

It captures two types of metrics:

1. Monotonically increasing ones aka counters - metrics such as CPU time (user and system), disk
   write and read request counts, etc. Those values monotonically increase over the process life
   time so we only capture the values once before stopping.

2. Values which can change over time aka gauges - memory usage (resident and virtual), number of
   open files, number of active threads.

   Those values can change over time, so we periodically capture them and calculate derivative
   values at the end of the capture period (min, max, avg, stddev).

Dependencies:

    - scalyr_agent Python package
    - requests
    - numpy
"""

from __future__ import absolute_import

if False:
    from typing import Dict
    from typing import Tuple
    from typing import List
    from typing import Union
    from typing import Optional

    T_metric_value = Union[int, float]

import os

import sys
import time
import logging
import argparse

from datetime import datetime
from collections import defaultdict

import numpy as np

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(BASE_DIR, '../../')))

from scalyr_agent.builtin_monitors.linux_process_metrics import ProcessTracker
from scalyr_agent.builtin_monitors.linux_process_metrics import Metric

from utils import initialize_logging
from utils import add_common_parser_arguments
from utils import parse_auth_credentials
from utils import parse_commit_date
from utils import send_payload_to_codespeed

logger = logging.getLogger(__name__)


METRICS_GAUGES = {
    # CPU usage related metrics
    'cpu_threads': Metric(name='app.threads', _type=None),

    # Memory usage related metrics
    'memory_usage_rss': Metric(name='app.mem.bytes', _type='resident'),
    'memory_usage_vms': Metric(name='app.mem.bytes', _type='vmsize'),

    # IO related metrics
    'io_open_fds': Metric(name='app.io.fds', _type='open'),
}  # type: Dict[str, Metric]

METRICS_COUNTERS = {
    # CPU usage related metrics
    'cpu_time_user': Metric(name='app.cpu', _type='user'),
    'cpu_time_system': Metric(name='app.cpu', _type='system'),

    # IO related metrics
    'io_read_count_requests': Metric(name='app.disk.requests', _type='read'),
    'io_write_count_requests': Metric(name='app.disk.requests', _type='write'),

    'io_read_count_bytes': Metric(name='app.disk.bytes', _type='read'),
    'io_write_count_bytes': Metric(name='app.disk.bytes', _type='write')
}  # type: Dict[str, Metric]


def bytes_to_megabytes(value):
    if not value:
        return value

    return (float(value) / 1048576)


# Functions for formatting metrics values
# We use those so we operate in more user-friendly units. It makes no sense to track memory usae
# in bytes when in reality, actual usage will never be smaller than a couple of MBs
METRIC_FORMAT_FUNCTIONS = {
    'memory_usage_rss': bytes_to_megabytes,
    'memory_usage_vms': bytes_to_megabytes,
}


def send_data_to_codespeed(codespeed_url, codespeed_auth, codespeed_project, codespeed_executable,
                           codespeed_environment, branch, commit_id, result, commit_date=None):
    # type: (str, Optional[Tuple[str, str]], str, str, str, str, str, dict, Optional[datetime]) -> None
    """
    Submit captured data to CodeSpeed instance.
    """
    payload = []
    for metric_name, metric_result in result.items():
        benchmark = metric_name

        item = {
            'commitid': commit_id,
            'branch': branch,

            'project': codespeed_project,
            'executable': codespeed_executable,
            'benchmark': benchmark,
            'environment': codespeed_environment,

            'result_value': metric_result['value'],
        }

        if commit_date:
            item['revision_date'] = commit_date.strftime('%Y-%m-%dT%H:%I:%S')

        # Include optional pre-computed data for gauge metrics
        for key in ['min', 'max', 'std_dev']:
            if metric_result.get(key, None) is not None:
                item['min'] = metric_result[key]

        payload.append(item)

    send_payload_to_codespeed(codespeed_url=codespeed_url, codespeed_auth=codespeed_auth,
                              commit_id=commit_id, payload=payload)


def capture_metrics(tracker, metrics, values):
    # type: (ProcessTracker, Dict[str, Metric], dict) -> dict
    """
    Capture gauge metric types and store them in the provided dictionary.
    """
    # Check if process we are monitoring is still alive
    try:
        os.kill(tracker.pid, 0)
    except OSError:
        raise ValueError('Process with pid "%s" is not alive' % (tracker.pid))

    process_metrics = tracker.collect()

    for metric_name, metric_obj in metrics.items():
        value = process_metrics[metric_obj]
        format_func = METRIC_FORMAT_FUNCTIONS.get(metric_name, lambda val: val)
        values[metric_name].append(format_func(value))

    return values


def main(pid, codespeed_url, codespeed_auth, codespeed_project, codespeed_executable,
         codespeed_environment, branch, commit_id, commit_date=None):
    # type: (int, str, Optional[Tuple[str, str]], str, str, str, str, str, Optional[datetime]) -> None
    """
    Main entry point / run loop for the script.
    """
    logger.info('Monitoring process with pid "%s" for metrics' % (pid))
    tracker = ProcessTracker(pid=pid, logger=logger)

    end_time = int(time.time() + args.capture_time)

    # Dictionary where captured metrics are saved
    # It maps metric name to a dictionary with the results
    captured_values = defaultdict(list)  # type: Dict[str, List[T_metric_value]]

    while time.time() <= end_time:
        logger.debug('Capturing gauge metrics...')
        capture_metrics(tracker=tracker, metrics=METRICS_GAUGES, values=captured_values)
        time.sleep(args.capture_interval)

    # Capture counter metrics
    logger.debug('Capturing counter metrics...')
    capture_metrics(tracker=tracker, metrics=METRICS_COUNTERS, values=captured_values)

    # Generate final result object and calculate derivatives for gauge metrics
    result = {}  # type: Dict[str, Dict[str, T_metric_value]]

    # Calculate derivatives for gauge metrics
    for metric_name in METRICS_GAUGES.keys():
        values = captured_values[metric_name]

        percentile_999 = np.percentile(values, 99.9)
        minimum = min(values)
        maximum = max(values)
        std_dev = np.std(values)

        result[metric_name] = {
            'value': percentile_999,
            'min': minimum,
            'max': maximum,
            'std_dev': std_dev
        }

    for metric_name in METRICS_COUNTERS.keys():
        metric_value = captured_values[metric_name][0]
        result[metric_name] = {
            'value': metric_value
        }

    logger.debug('Captured data: %s' % (str(result)))
    logger.info('Capture complete, submitting metrics to CodeSpeed...')
    send_data_to_codespeed(codespeed_url=codespeed_url, codespeed_auth=codespeed_auth,
                           codespeed_project=codespeed_project,
                           codespeed_executable=codespeed_executable,
                           codespeed_environment=codespeed_environment, branch=branch,
                           commit_id=commit_id,
                           result=result,
                           commit_date=commit_date)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=('Capture process level metric data and submit it '
                                                  'to CodeSpeed instance'))

    # Add common arguments
    parser = add_common_parser_arguments(parser=parser)

    # Add arguments which are specific to this script
    parser.add_argument('--pid',
                        type=int,
                        required=True,
                        help=('ID of a process to capture metrics for.'))
    parser.add_argument('--capture-time',
                        type=int,
                        required=True,
                        default=10,
                        help=('How long capture metrics for (in seconds).'))
    parser.add_argument('--capture-interval',
                        type=float,
                        required=True,
                        default=1,
                        help=('How often to capture gauge metrics during the capture time '
                              '(in seconds).'))
    parser.add_argument('--commit-date',
                        type=str,
                        required=False,
                        help=('Date of a git commit. If not provided, it defaults to current '
                              'date.'))

    args = parser.parse_args()

    codespeed_auth = parse_auth_credentials(args.codespeed_auth)
    commit_date = parse_commit_date(args.commit_date)

    initialize_logging(debug=args.debug)
    main(pid=args.pid, codespeed_url=args.codespeed_url, codespeed_auth=codespeed_auth,
         codespeed_project=args.codespeed_project, codespeed_executable=args.codespeed_executable,
         codespeed_environment=args.codespeed_environment, branch=args.branch,
         commit_id=args.commit_id, commit_date=commit_date)
