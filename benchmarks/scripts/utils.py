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

import pprint

from datetime import datetime
from argparse import ArgumentParser  # NOQA

if False:  # NOSONAR
    from typing import List
    from typing import Dict
    from typing import Tuple
    from typing import Optional

import json
import logging

import requests

from scalyr_agent import compat

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

    # pylint: disable=no-member
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]  # type: ignore
    # pylint: enable=no-member
    for logger in loggers:
        logger.setLevel(log_level)

    logging.basicConfig(level=log_level)


def send_payload_to_codespeed(
    codespeed_url, codespeed_auth, commit_id, payload, dry_run=False
):
    # type: (str, Optional[Tuple[str, str]], str, List[Dict], bool) -> None
    """
    Send provided payload to CodeSpeed.
    """
    # Remove trailing slash (if any)
    if codespeed_url.endswith("/"):
        codespeed_url = codespeed_url[:-1]

    url = "%s/result/add/json/" % (codespeed_url)
    data = {"json": json.dumps(payload)}

    if dry_run:
        logger.info("Dry run, not submitting metrics to CodeSpeed...")
        logger.info(
            "Would have submit the following data: %s" % (pprint.pformat(payload))
        )
        return
    else:
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


def add_common_parser_arguments(
    parser,
    include_branch_arg=True,
    include_commit_id_arg=True,
    include_commit_date_arg=True,
    use_defaults_from_env_variables=False,
):
    # type: (ArgumentParser, bool, bool, bool, bool) -> ArgumentParser
    """
    Add arguments to the provided parser instance which are common to all the scripts which send
    data to CodeSpeed (--codespeed-url, --codespeed-auth, etc.).

    :param use_defaults_from_env_variables: True to use default values from corresponding env
                                            variables.
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

    if include_branch_arg:
        parser.add_argument(
            "--branch",
            type=str,
            required=True,
            default="master",
            help=("Name of the branch this capture belongs to."),
        )

    if include_commit_id_arg:
        parser.add_argument(
            "--commit-id",
            type=str,
            required=True,
            help=("Git commit hash (revision) this capture belongs to."),
        )

    if include_commit_date_arg:
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
        "--dry-run",
        action="store_true",
        default=False,
        help=("Just print the values, but don't submit them to CodeSpeed."),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=("Set script log level to DEBUG."),
    )

    if not use_defaults_from_env_variables:
        return parser

    # Add in default values for all the arguments which name starts with code_speed.
    # For example, if the argument name is "codespeed-url" and variable destination is
    # "codespeed_url", it will look for a default value in the environment variable named
    # CODESPEED_URL
    default_values = {}
    for action in parser._actions:
        dest = action.dest

        if not dest.startswith("codespeed"):
            continue

        env_var_name = dest.upper()
        env_var_value = compat.os_environ_unicode.get(env_var_name, None)

        if env_var_value is None:
            continue

        default_values[dest] = env_var_value
        action.required = False

    parser.set_defaults(**default_values)

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
