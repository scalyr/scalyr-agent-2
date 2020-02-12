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

if False:
    from typing import Tuple
    from typing import List
    from typing import Optional

import json
import logging
import argparse

import requests

logger = logging.getLogger(__name__)


def send_value_to_codespeed(codespeed_url, codespeed_auth, codespeed_project, codespeed_executable,
                            codespeed_environment, codespeed_benchmark, branch, commit_id, value):
    # type: (str, Optional[Tuple[str, str]], str, str, str, str, str, str, int) -> None
    payload = [{
        'commitid': commit_id,
        'branch': branch,

        'project': codespeed_project,
        'executable': codespeed_executable,
        'benchmark': codespeed_benchmark,
        'environment': codespeed_environment,

        'result_value': value,
    }]

    url = '%s/result/add/json/' % (codespeed_url)
    data = {'json': json.dumps(payload)}

    print(payload)

    logger.debug('Sending data to "%s" (data=%s)' % (codespeed_url, data))

    resp = requests.post(url=url, data=data, auth=codespeed_auth)

    if resp.status_code != 202:
        raise ValueError(('Failed to POST data to CodeSpeed instance (status_code=%s): %s' %
                          (resp.status_code, resp.text)))

    view_report_url = '%s/changes/?rev=%s' % (codespeed_url, commit_id)
    logger.info('Successfully submitted data to %s' % (codespeed_url))
    logger.info('Report should now be available at %s' % (view_report_url))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=('Send single value to CodeSpeed'))
    parser.add_argument('--codespeed-url',
                        type=str,
                        required=True,
                        help=('URL of a CodeSpeed instance to send metrics to.'))
    parser.add_argument('--codespeed-auth',
                        type=str,
                        required=False,
                        default='',
                        help=('CodeSpeed auth credentials in the format of username:password'))
    parser.add_argument('--codespeed-project',
                        type=str,
                        required=True,
                        help=('Name of the CodeSpeed project to submit metrics for.'))
    parser.add_argument('--codespeed-executable',
                        type=str,
                        required=True,
                        help=('Name of the CodeSpeed executable to submit metrics for.'))
    parser.add_argument('--codespeed-environment',
                        type=str,
                        required=True,
                        help=('Name of the CodeSpeed environment to submit metrics for.'))
    parser.add_argument('--codespeed-benchmark',
                        type=str,
                        required=True,
                        help=('Name of the CodeSpeed benchmark.'))
    parser.add_argument('--branch',
                        type=str,
                        required=True,
                        default='master',
                        help=('Name of the branch this capture belongs to.'))
    parser.add_argument('--commit-id',
                        type=str,
                        required=True,
                        help=('Git commit hash (revision) this capture belongs to.'))
    parser.add_argument('--value',
                        type=int,
                        required=True,
                        help=('Benchmark result value'))

    args = parser.parse_args()

    if args.codespeed_auth:
        if len(args.codespeed_auth.split(':')) != 2:
            raise ValueError('--codespeed-auth argument must be in the following format: '
                            '--codespeed_auth=<username:password>')

        # Split it into (username, password) tuple
        split = args.codespeed_auth.split(':')[:2]  # type: List[str]
        codespeed_auth = (split[0], split[1])

    # Remove trailing slash (if any)
    codespeed_url = args.codespeed_url
    if codespeed_url.endswith('/'):
        codespeed_url = codespeed_url[:-1]

    # initialize_logging(debug=args.debug)
    send_value_to_codespeed(codespeed_url=codespeed_url, codespeed_auth=codespeed_auth,
         codespeed_project=args.codespeed_project, codespeed_executable=args.codespeed_executable,
         codespeed_environment=args.codespeed_environment,
         codespeed_benchmark=args.codespeed_benchmark,
         branch=args.branch,
         commit_id=args.commit_id,
         value=args.value)
