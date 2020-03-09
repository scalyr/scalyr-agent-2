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
This module contains various utility functions for sending data to CodeSpeed.
"""

from __future__ import absolute_import

from datetime import datetime, timedelta
from argparse import ArgumentParser  # NOQA
import re
import os
import time
from io import open

if False:
    from typing import List
    from typing import Dict
    from typing import Tuple
    from typing import Optional

import json
import logging

import requests

__all__ = [
    "initialize_logging",
    "send_payload_to_codespeed",
    "add_common_parser_arguments",
    "parse_auth_credentials",
    "parse_auth_credentials",
]

logger = logging.getLogger(__name__)


def initialize_logging(debug=False):
    # type: (bool) -> None
    """
    Initialize logging for this script.
    """
    if debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]  # type: ignore
    for logger in loggers:
        logger.setLevel(log_level)

    logging.basicConfig(level=log_level)


def send_payload_to_codespeed(codespeed_url, codespeed_auth, commit_id, payload):
    # type: (str, Optional[Tuple[str, str]], str, List[Dict]) -> None
    """
    Send provided payload to CodeSpeed.
    """
    # Remove trailing slash (if any)
    if codespeed_url.endswith("/"):
        codespeed_url = codespeed_url[:-1]

    url = "%s/result/add/json/" % (codespeed_url)
    data = {"json": json.dumps(payload)}

    logger.debug('Sending data to "%s" (data=%s)' % (codespeed_url, data))

    resp = requests.post(url=url, data=data, auth=codespeed_auth)

    if resp.status_code != 202:
        raise ValueError(
            (
                "Failed to POST data to CodeSpeed instance (status_code=%s): %s"
                % (resp.status_code, resp.text)
            )
        )

    view_report_url = "%s/changes/?rev=%s" % (codespeed_url, commit_id)
    logger.info("Successfully submitted data to %s" % (codespeed_url))
    logger.info("Report should now be available at %s" % (view_report_url))


def add_common_parser_arguments(parser):
    # type: (ArgumentParser) -> ArgumentParser
    """
    Add arguments to the provided parser instance which are common to all the scripts which send
    data to CodeSpeed (--codespeed-url, --codespeed-auth, etc.).
    """
    parser.add_argument(
        "--codespeed-url",
        type=str,
        required=True,
        help=("URL of a CodeSpeed instance to send metrics to."),
    )
    parser.add_argument(
        "--codespeed-auth",
        type=str,
        required=False,
        default="",
        help=("CodeSpeed auth credentials in the format of username:password"),
    )
    parser.add_argument(
        "--codespeed-project",
        type=str,
        required=True,
        help=("Name of the CodeSpeed project to submit metrics for."),
    )
    parser.add_argument(
        "--codespeed-executable",
        type=str,
        required=True,
        help=("Name of the CodeSpeed executable to submit metrics for."),
    )
    parser.add_argument(
        "--codespeed-environment",
        type=str,
        required=True,
        help=("Name of the CodeSpeed environment to submit metrics for."),
    )
    parser.add_argument(
        "--branch",
        type=str,
        required=True,
        default="master",
        help=("Name of the branch this capture belongs to."),
    )
    parser.add_argument(
        "--commit-id",
        type=str,
        required=True,
        help=("Git commit hash (revision) this capture belongs to."),
    )
    parser.add_argument(
        "--commit-date",
        type=str,
        required=False,
        help=(
            "Date of a git commit in YYYY-MM-DD HH:MM:SS format. If not "
            "provided, it defaults to current date."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=("Set script log level to DEBUG."),
    )

    return parser


def parse_auth_credentials(value):
    # type: (str) -> Optional[Tuple[str, str]]
    """
    Parse codespeed auth credentials from the provided string.
    """
    if not value:
        return None

    if len(value.split(":")) != 2:
        raise ValueError(
            "--codespeed-auth argument must be in the following format: "
            "--codespeed_auth=<username:password>"
        )

    # Split it into (username, password) tuple
    split = value.split(":")[:2]  # type: List[str]
    codespeed_auth = (split[0], split[1])

    return codespeed_auth


def parse_commit_date(value):
    # type: (str) -> Optional[datetime]
    """
    Parse commit date from a string in the following format into a datetime object.
    """
    if not value:
        return None

    # Validate date is in the correct format (YYYY-mm-ddTHH:mm:ss)
    try:
        commit_date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        msg = (
            "Got invalid date string: %s. Date must be in the following format: %s"
            % (value, "%Y-%m-%d %H:%M:%S")
        )
        raise ValueError(msg)

    return commit_date


def parse_capture_time(value):
    # type: (str) -> float
    logger.info(value)
    m = re.match(r"(\d+)([smhd])", value)
    if not m:
        raise ValueError(
            "Got invalid run time: %s, Run time must be in the following format: %s"
            % (value, "<number><s|m|h|d>, example: 1h - 1 hour")
        )

    number, time_unit = m.groups()
    if time_unit == "s":
        time_unit = "seconds"
    elif time_unit == "m":
        time_unit = "minutes"
    elif time_unit == "h":
        time_unit = "hours"
    elif time_unit == "d":
        time_unit = "days"
    return timedelta(**{time_unit: int(number)}).total_seconds()


def wait_for_agent_start_and_get_pid(pid_file_path):
    # type: (str) -> int
    """IF file 'pid_file_path' exists, we assume that the agent is started. Returns 'pid' of the agent process."""
    attempts = 0
    while not os.path.exists(pid_file_path):
        if attempts > 10:
            raise RuntimeError("Agent pid file did not appear.")
        time.sleep(1)

    with open(pid_file_path, "r") as f:
        return int(f.readline())
