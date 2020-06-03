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
from __future__ import print_function
from io import open

if False:  # NOSONAR
    # NOTE: This is a workaround for old Python versions where typing module is not available
    # We should eventually improve that once we start producing distributions with Python
    # interpreter and dependencies bundled in.
    # Adding conditional "typing" dependency would require too much boiler plate code at this point.
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
import signal
import json
import argparse

from datetime import datetime
from collections import defaultdict

import six
import numpy as np
import psutil

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(BASE_DIR, "../../")))

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
    "cpu_threads": Metric(name="app.threads", _type=None),
    # Memory usage related metrics
    "memory_usage_rss": Metric(name="app.mem.bytes", _type="resident"),
    "memory_usage_rss_shared": Metric(name="app.mem.bytes", _type="resident_shared"),
    "memory_usage_rss_private": Metric(name="app.mem.bytes", _type="resident_private"),
    "memory_usage_vms": Metric(name="app.mem.bytes", _type="vmsize"),
    # IO related metrics
    "io_open_fds": Metric(name="app.io.fds", _type="open"),
    # GC related metrics
    "gc_garbage": Metric(name="app.gc.garbage", _type=None),
}  # type: Dict[str, Metric]

METRICS_COUNTERS = {
    # CPU usage related metrics
    "cpu_time_user": Metric(name="app.cpu", _type="user"),
    "cpu_time_system": Metric(name="app.cpu", _type="system"),
    # IO related metrics
    "io_read_count_requests": Metric(name="app.disk.requests", _type="read"),
    "io_write_count_requests": Metric(name="app.disk.requests", _type="write"),
    "io_read_count_bytes": Metric(name="app.disk.bytes", _type="read"),
    "io_write_count_bytes": Metric(name="app.disk.bytes", _type="write"),
}  # type: Dict[str, Metric]


def bytes_to_megabytes(value):
    if not value:
        return value

    return float(value) / 1048576


# Functions for formatting metrics values
# We use those so we operate in more user-friendly units. It makes no sense to track memory usae
# in bytes when in reality, actual usage will never be smaller than a couple of MBs
METRIC_FORMAT_FUNCTIONS = {
    "memory_usage_rss": bytes_to_megabytes,
    "memory_usage_vms": bytes_to_megabytes,
    "memory_usage_rss_shared": bytes_to_megabytes,
    "memory_usage_rss_private": bytes_to_megabytes,
}


def send_data_to_codespeed(
    codespeed_url,
    codespeed_auth,
    codespeed_project,
    codespeed_executable,
    codespeed_environment,
    branch,
    commit_id,
    result,
    commit_date=None,
    dry_run=False,
):
    # type: (str, Optional[Tuple[str, str]], str, str, str, str, str, dict, Optional[datetime], bool) -> None
    """
    Submit captured data to CodeSpeed instance.
    """
    payload = []
    for metric_name, metric_result in result.items():
        benchmark = metric_name

        item = {
            "commitid": commit_id,
            "branch": branch,
            "project": codespeed_project,
            "executable": codespeed_executable,
            "benchmark": benchmark,
            "environment": codespeed_environment,
            "result_value": metric_result["value"],
        }

        if commit_date:
            item["revision_date"] = commit_date.strftime("%Y-%m-%d %H:%M:%S")

        # Include optional pre-computed data for gauge metrics
        for key in ["min", "max", "std_dev"]:
            if metric_result.get(key, None) is not None:
                item[key] = metric_result[key]

        payload.append(item)

    send_payload_to_codespeed(
        codespeed_url=codespeed_url,
        codespeed_auth=codespeed_auth,
        commit_id=commit_id,
        payload=payload,
        dry_run=dry_run,
    )


def capture_metrics(
    tracker, process, metrics, values, capture_agent_status_metrics=False
):
    # type: (ProcessTracker, psutil.Process, Dict[str, Metric], dict, bool) -> dict
    """
    Capture gauge metric types and store them in the provided dictionary.
    """
    # Check if process we are monitoring is still alive
    try:
        os.kill(tracker.pid, 0)
    except OSError:
        raise ValueError('Process with pid "%s" is not alive' % (tracker.pid))

    process_metrics = tracker.collect()

    # Add in metrics we capture via psutil
    psutil_metrics = get_additional_psutil_metrics(process=process)
    process_metrics.update(psutil_metrics)

    # Add in agent_status metrics (if enabled)
    if capture_agent_status_metrics:
        agent_status_metrics = get_agent_status_metrics(process=process)
        process_metrics.update(agent_status_metrics)

    metric_values = {}
    for metric_name, metric_obj in metrics.items():
        if metric_obj not in process_metrics:
            continue
        value = process_metrics[metric_obj]
        format_func = METRIC_FORMAT_FUNCTIONS.get(metric_name, lambda val: val)
        value = format_func(value)
        metric_values[metric_name] = value
        values[metric_name].append(value)

    logger.debug("Captured metrics: %s" % (str(metric_values)))

    return values


def get_additional_psutil_metrics(process):
    # type: (psutil.Process) -> Dict[Metric, T_metric_value]
    """
    Capture any additional metrics which are currently not exposed via Linux Process Metric tracker
    using psutil.
    """
    # Capture and calculate shared and private memory usage
    metric_shared = Metric(name="app.mem.bytes", _type="resident_shared")
    metric_private = Metric(name="app.mem.bytes", _type="resident_private")

    result = {
        metric_shared: 0,
        metric_private: 0,
    }  # type: Dict[Metric, T_metric_value]

    memory_maps = process.memory_maps()
    for memory_map in memory_maps:
        result[metric_shared] += memory_map.shared_clean + memory_map.shared_dirty
        result[metric_private] += memory_map.private_clean + memory_map.private_dirty

    return result


def get_agent_status_metrics(process):
    # type: (psutil.Process) -> dict
    """
    Retrieve additional agent related metrics utilizing agent status functionality.
    """
    result = {}

    # Request json format
    agent_data_path = os.path.expanduser("~/scalyr-agent-dev/data")
    status_format_file = os.path.join(agent_data_path, "status_format")
    with open(status_format_file, "w") as fp:
        fp.write(six.text_type("json"))

    # Ask agent to dump metrics
    os.kill(process.pid, signal.SIGUSR1)

    # Wait a bit for agent to write the metrics and parse the metrics
    time.sleep(2)

    status_file = os.path.join(agent_data_path, "last_status")

    with open(status_file, "r") as fp:
        content = fp.read()

    content = json.loads(content)

    # NOTE: Currently we only capture gc metrics
    metric_gc_garbage = Metric(name="app.gc.garbage", _type=None)
    result[metric_gc_garbage] = content.get("gc_stats", {}).get("garbage", 0)

    return result


def main(
    pid,
    codespeed_url,
    codespeed_auth,
    codespeed_project,
    codespeed_executable,
    codespeed_environment,
    branch,
    commit_id,
    commit_date=None,
    capture_agent_status_metrics=False,
    dry_run=False,
):
    # type: (int, str, Optional[Tuple[str, str]], str, str, str, str, str, Optional[datetime], bool, bool) -> None
    """
    Main entry point / run loop for the script.
    """
    logger.info('Monitoring process with pid "%s" for metrics' % (pid))
    tracker = ProcessTracker(pid=pid, logger=logger)
    process = psutil.Process(pid)

    end_time = int(time.time() + args.capture_time)

    # Dictionary where captured metrics are saved
    # It maps metric name to a dictionary with the results
    captured_values = defaultdict(list)  # type: Dict[str, List[T_metric_value]]

    # Give it some time for the process to start and initialize before first capture
    time.sleep(5)

    while time.time() <= end_time:
        logger.debug("Capturing gauge metrics...")
        capture_metrics(
            tracker=tracker,
            process=process,
            metrics=METRICS_GAUGES,
            values=captured_values,
            capture_agent_status_metrics=capture_agent_status_metrics,
        )
        time.sleep(args.capture_interval)

    # Capture counter metrics
    logger.debug("Capturing counter metrics...")
    capture_metrics(
        tracker=tracker,
        process=process,
        metrics=METRICS_COUNTERS,
        values=captured_values,
    )

    # Generate final result object and calculate derivatives for gauge metrics
    result = {}  # type: Dict[str, Dict[str, T_metric_value]]

    # Calculate derivatives for gauge metrics
    for metric_name in METRICS_GAUGES.keys():
        if metric_name not in captured_values:
            continue

        values = captured_values[metric_name]

        percentile_999 = np.percentile(values, 99.9)
        minimum = min(values)
        maximum = max(values)
        std_dev = np.std(values)

        result[metric_name] = {
            "value": percentile_999,
            "min": minimum,
            "max": maximum,
            "std_dev": std_dev,
        }

    for metric_name in METRICS_COUNTERS.keys():
        metric_value = captured_values[metric_name][0]
        result[metric_name] = {"value": metric_value}

    logger.debug("Captured data: %s" % (str(result)))

    logger.info("Capture complete, submitting metrics to CodeSpeed...")
    send_data_to_codespeed(
        codespeed_url=codespeed_url,
        codespeed_auth=codespeed_auth,
        codespeed_project=codespeed_project,
        codespeed_executable=codespeed_executable,
        codespeed_environment=codespeed_environment,
        branch=branch,
        commit_id=commit_id,
        result=result,
        commit_date=commit_date,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Capture process level metric data and submit it " "to CodeSpeed instance"
        )
    )

    # Add common arguments
    parser = add_common_parser_arguments(parser=parser)

    # Add arguments which are specific to this script
    parser.add_argument(
        "--pid",
        type=int,
        required=True,
        help=("ID of a process to capture metrics for."),
    )
    parser.add_argument(
        "--capture-time",
        type=int,
        required=True,
        default=10,
        help=("How long capture metrics for (in seconds)."),
    )
    parser.add_argument(
        "--capture-interval",
        type=float,
        required=True,
        default=1,
        help=(
            "How often to capture gauge metrics during the capture time "
            "(in seconds)."
        ),
    )
    parser.add_argument(
        "--capture-agent-status-metrics",
        action="store_true",
        default=False,
        help=("True to also capture additional metrics using agent status file."),
    )

    args = parser.parse_args()

    codespeed_auth = parse_auth_credentials(args.codespeed_auth)
    commit_date = parse_commit_date(args.commit_date)

    initialize_logging(debug=args.debug)
    main(
        pid=args.pid,
        codespeed_url=args.codespeed_url,
        codespeed_auth=codespeed_auth,
        codespeed_project=args.codespeed_project,
        codespeed_executable=args.codespeed_executable,
        codespeed_environment=args.codespeed_environment,
        branch=args.branch,
        commit_id=args.commit_id,
        commit_date=commit_date,
        capture_agent_status_metrics=args.capture_agent_status_metrics,
        dry_run=args.dry_run,
    )
