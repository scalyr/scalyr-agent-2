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
Script which sends a single value to CodeSpeed.
"""

from __future__ import absolute_import

if False:
    from typing import Tuple
    from typing import Optional

import logging
import argparse

from datetime import datetime

from utils import initialize_logging
from utils import add_common_parser_arguments
from utils import parse_auth_credentials
from utils import parse_commit_date
from utils import send_payload_to_codespeed

logger = logging.getLogger(__name__)


def send_value_to_codespeed(codespeed_url, codespeed_auth, codespeed_project, codespeed_executable,
                            codespeed_environment, codespeed_benchmark, branch, commit_id, value,
                            commit_date=None):
    # type: (str, Optional[Tuple[str, str]], str, str, str, str, str, str, int, Optional[datetime]) -> None
    payload = [{
        'commitid': commit_id,
        'branch': branch,
        'project': codespeed_project,
        'executable': codespeed_executable,
        'benchmark': codespeed_benchmark,
        'environment': codespeed_environment,
        'result_value': value,
    }]

    if commit_date:
        payload[0]['revision_date'] = commit_date.strftime('%Y-%m-%d %H:%M:%S')

    send_payload_to_codespeed(codespeed_url=codespeed_url, codespeed_auth=codespeed_auth,
                              commit_id=commit_id, payload=payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=('Send single value to CodeSpeed'))

    # Add common arguments
    parser = add_common_parser_arguments(parser=parser)

    # Add arguments which are specific to this script
    parser.add_argument('--codespeed-benchmark',
                        type=str,
                        required=True,
                        help=('Name of the CodeSpeed benchmark.'))
    parser.add_argument('--value',
                        type=int,
                        required=True,
                        help=('Benchmark result value'))

    args = parser.parse_args()

    codespeed_auth = parse_auth_credentials(args.codespeed_auth)
    commit_date = parse_commit_date(args.commit_date)

    initialize_logging(debug=args.debug)
    send_value_to_codespeed(codespeed_url=args.codespeed_url, codespeed_auth=codespeed_auth,
         codespeed_project=args.codespeed_project, codespeed_executable=args.codespeed_executable,
         codespeed_environment=args.codespeed_environment,
         codespeed_benchmark=args.codespeed_benchmark,
         branch=args.branch,
         commit_id=args.commit_id,
         value=args.value,
         commit_date=commit_date)
