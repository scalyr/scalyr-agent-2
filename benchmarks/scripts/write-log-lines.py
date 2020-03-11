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

from __future__ import absolute_import

import os
import time
import threading
import argparse
import shelve
import logging
from datetime import datetime

from io import open

from utils import wait_for_agent_start_and_get_pid, parse_duration, initialize_logging

DUMMY_LINE = (
    "2020-03-08 16:11:08.246Z INFO [dummy] [dummy.py:589] Just a dummy log line. {0}\n"
)

BACKUP_PATH = "/log-writer-data/backup.txt"

logger = logging.getLogger(__name__)


class LogWriter(threading.Thread):
    """Thread that writes lines to a file"""

    def __init__(self, file_path, interval, start_time, end_time):
        # type: (str, float, float, float) -> None
        super(LogWriter, self).__init__(daemon=True)
        self._file_path = file_path
        self._interval = interval
        self._duration = duration

        self._start_time = start_time
        self._end_time = end_time

        self._line_counter = 0

    def run(self):
        # wait for start time.
        logger.debug(
            "[Log file: {0}] Writer started. Time: {1}".format(
                self._file_path, datetime.now()
            )
        )
        if time.time() < self._start_time:
            logger.debug("[Log file: {0}] Wait for start.".format(self._file_path))
        while time.time() < self._start_time:
            time.sleep(0.1)

        logger.debug(
            "[Log file: {0}] Started writing. Start time: {1}".format(
                self._file_path, datetime.now()
            )
        )
        while time.time() < self._end_time:
            with open(
                self._file_path, "a" if os.path.exists(self._file_path) else "w"
            ) as f:
                f.write(DUMMY_LINE.format(self._line_counter))
            self._line_counter += 1
            time.sleep(self._interval)

        logger.debug(
            "[Log file: {0}] Stopped writing. Stop time: {1}".format(
                self._file_path, datetime.now()
            )
        )


def _create_log_writer(agent_logs_path, input_string):
    """Parse --add-log input string from command line and use them to create LogWriter."""
    log_writer_input = dict([expr.split("=") for expr in input_string.split(",")])
    file_name = log_writer_input.get("name")
    if not file_name:
        raise ValueError("No log name in --add-log : {0}".format(input_string))

    file_path = os.path.join(agent_logs_path, "test_log_{}.log".format(file_name))

    interval = log_writer_input.get("interval")
    if not interval:
        raise ValueError("No interval in --add-log : {0}".format(input_string))
    interval = float(interval)

    start_delay_value = log_writer_input.get("start_delay")
    if start_delay_value:
        start_delay = parse_duration(start_delay_value)
        writer_start_time = start_time + start_delay
    else:
        writer_start_time = start_time

    duration_value = log_writer_input.get("duration")
    if duration_value:
        duration = parse_duration(duration_value)
        write_end_time = writer_start_time + duration
    else:
        write_end_time = end_time

    logger.debug("Start log file writer: {0}".format(input_string))

    logger.debug(
        "Create writer. Name: {0}, start time: {1}, end_time: {2}".format(
            file_path,
            datetime.fromtimestamp(writer_start_time),
            datetime.fromtimestamp(write_end_time),
        )
    )
    writer = LogWriter(
        file_path, interval, start_time=writer_start_time, end_time=write_end_time
    )
    return writer


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-duration",
        type=str,
        default="1m",
        help="The duration of the script running. Format: <number><s|m|h|d>. Example: 3h.",
    )

    parser.add_argument(
        "--agent-data-path",
        type=str,
        required=True,
        help="Path to the agent data directory.",
    )

    parser.add_argument(
        "--add-log",
        action="append",
        help=(
            "Add new log. "
            'Format: "name=<name>(required!),interval=<seconds>(required!),start_delay=<delay>,duration=<duration>"'
        ),
    )

    parser.add_argument(
        "--backup-path",
        type=str,
        default="",
        help="Path to file to write captured metrics into to avoid data loss.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=("Set script log level to DEBUG."),
    )

    args = parser.parse_args()

    initialize_logging(debug=args.debug)

    logger.info("Started")

    agent_logs_path = os.path.join(args.agent_data_path, "log")
    pid_file_path = os.path.join(agent_logs_path, "agent.pid")
    pid = wait_for_agent_start_and_get_pid(pid_file_path)
    logger.info("Agent was found. PID: {0}".format(pid))

    shv = None
    if args.backup_path:
        shv = shelve.open(args.backup_path)

    end_time = None
    if shv is not None:
        # check if there is a saved shelve with end time from previous run.
        logger.debug("Try to get end -time from shelve.")
        end_time = shv.get("end_time")
        if end_time is None:
            logger.debug("No end time in shelve.")

    duration = parse_duration(args.run_duration)

    if end_time is None:
        # no saved end time

        end_time = time.time() + duration
        # save end time into shelve to be able to continue in case of failures.
        if shv is not None:
            logger.debug("Save end time in shelve. Value: {0}".format(end_time))
            shv["end_time"] = end_time

    if shv is not None:
        shv.sync()

    start_time = end_time - duration

    if args.add_log:
        log_writers = list()
        logger.info("Start log writes. Current time: {0}".format(datetime.now()))
        for log_str in args.add_log:
            log_writer = _create_log_writer(agent_logs_path, log_str)
            log_writer.start()
            log_writers.append(log_writer)

        for lw in log_writers:
            lw.join()
    else:
        logger.info("No log writers were added.")

    while time.time() < end_time:
        time.sleep(1)

    logger.info("Log writer stopped.")
