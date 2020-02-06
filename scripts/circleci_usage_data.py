#!/usr/bin/env python
# Copyright 2014 Scalyr Inc.
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
Script which prints Circle CI usage data for the recent workflows.

It relies on the following environment variables being set:

- CIRCLE_CI_API_TOKEN
- MAILGUN_API_TOKEN (only when reports are sent to email)
"""

from __future__ import absolute_import
from __future__ import print_function
from scalyr_agent import compat

if False:
    from typing import Optional
    from typing import List

import sys
import argparse
import datetime

from io import StringIO

import requests

CREDIT_BUNDLE_PRICE = 15.0
CREDIT_BUNDLE_UNIT_COUNT = 25000.0

# Price for a single CPU usage credit
PRICE_PER_CREDIT = CREDIT_BUNDLE_PRICE / CREDIT_BUNDLE_UNIT_COUNT

GITHUB_API_PRS_URL = (
    "https://api.github.com/repos/scalyr/scalyr-agent-2/pulls?state=all&per_page=500"
)
CIRCLE_CI_API_INSIGHTS_URL = (
    "https://circleci.com/api/v2/insights/{project_slug}/workflows/{workflow}"
)

CIRCLE_CI_WORKFLOW_VIEW_URL = "https://circleci.com/workflow-run/{workflow_id}"

CIRCLE_CI_API_TOKEN = compat.os_environ_unicode.get("CIRCLE_CI_API_TOKEN", None)
MAILGUN_API_TOKEN = compat.os_environ_unicode.get("MAILGUN_API_TOKEN", None)


def get_usage_data_for_branch(
    buff, project_slug, workflow, status="success", branch="master", limit=10
):
    # type: (StringIO, str, str, str, str, int) -> None
    """
    Get usage data for the provided project and write it to the provided buffer.
    """
    buff.write(
        u'Usage data for recent workflow runs for workflow "%s" with status="%s" and branch "%s"\n\n'
        % (workflow, status, branch)
    )

    url = CIRCLE_CI_API_INSIGHTS_URL.format(
        project_slug=project_slug, workflow=workflow
    )
    params = {"limit": "100", "branch": branch}
    headers = {"Circle-Token": CIRCLE_CI_API_TOKEN}

    response = requests.get(url, params=params, headers=headers)

    if response.status_code == 404:
        raise ValueError("Invalid CIRCLE_CI_API_TOKEN or project_slug")

    data = response.json()

    count = 0
    for item in data.get("items", []):
        if status != "all" and item["status"] != status:
            continue

        workflow_view_url = CIRCLE_CI_WORKFLOW_VIEW_URL.format(workflow_id=item["id"])
        price_estimate = round(item["credits_used"] * PRICE_PER_CREDIT, 2)

        buff.write(u"Workflow ID: %s (%s)\n" % (item["id"], workflow_view_url))
        buff.write(u"Start time: %s\n" % (item["created_at"]))
        buff.write(u"Duration: %s seconds\n" % item["duration"])
        buff.write(u"Status: %s\n" % (item["status"]))
        buff.write(u"Total duration: %s seconds\n" % item["duration"])
        buff.write(
            u"Credits used: %s (~%s USD)\n\n" % (item["credits_used"], price_estimate)
        )

        count += 1
        if count >= limit:
            break


def print_usage_data(
    project_slug, workflow, status="success", branch="master", limit=10, emails=None
):
    # type: (str, str, str, str, int, Optional[List[str]]) -> None
    if branch == "all":
        branches = []
    else:
        branches = [branch]

    buff = StringIO()

    buff.write(u"Circle CI usage and cost report\n\n")
    buff.write(
        u"Pricing estimate assumes %s credits cost %s$\n\n"
        % (CREDIT_BUNDLE_UNIT_COUNT, CREDIT_BUNDLE_PRICE)
    )

    for branch in branches:
        get_usage_data_for_branch(
            buff=buff,
            project_slug=project_slug,
            workflow=workflow,
            status=status,
            branch=branch,
            limit=limit,
        )

    value = buff.getvalue()

    if emails:
        date = datetime.datetime.now().strftime("%A, %b %d %Y")
        subject = u"Circle CI Usage Report on Day %s" % (date)
        send_email(to=emails, subject=subject, text=value)
        print(("Sent email report to %s" % (",".join(emails))))
    else:
        print(value)


def send_email(to, subject, text):
    # type: (List[str], str, str) -> None
    response = requests.post(
        "https://api.mailgun.net/v3/kami.mailgun.org/messages",
        auth=("api", MAILGUN_API_TOKEN),
        data={
            "from": "Circle CI Usage Report <mailgun@kami.mailgun.org>",
            "to": to,
            "subject": subject,
            "text": text,
        },
    )

    if response.status_code == 401:
        raise ValueError("Invalid value for MAILGUN_API_TOKEN environment variable")
    elif response.status_code != 200:
        raise ValueError("Failed to send email: %s" % (response.text))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Circle CI usage data")
    parser.add_argument(
        "--project_slug",
        help="Project slug in the following format: <vcs>/<org name>/<repo name>",
        default="gh/scalyr/scalyr-agent-2",
    )
    parser.add_argument(
        "--workflow",
        help="Name of the workflow to print the usage data for.",
        default="unittest",
    )
    parser.add_argument(
        "--status", help="Workflow status to filter on.", default="success"
    )
    parser.add_argument(
        "--branch", help="Branch to print the usage data for", default="master"
    )
    parser.add_argument(
        "--limit",
        help="Maximum number of workflow runs per branch to print data for.",
        type=int,
        default="10",
    )
    parser.add_argument(
        "--emails",
        help="If provided, report will also be emailed to those addresses",
        type=str,
        default=None,
        required=False,
    )

    args = parser.parse_args(sys.argv[1:])

    if args.status not in ["all", "success", "failed"]:
        raise ValueError("Invalid status: %s" % (args.status))

    if not CIRCLE_CI_API_TOKEN:
        raise ValueError("CIRCLE_CI_API_TOKEN environment variable is not set")

    emails = ",".split(args.emails) if args.emails else []
    if emails and not MAILGUN_API_TOKEN:
        raise ValueError("MAILGUN_API_TOKEN environment variable is not set")

    print_usage_data(
        project_slug=args.project_slug,
        workflow=args.workflow,
        status=args.status,
        branch=args.branch,
        limit=args.limit,
        emails=emails,
    )
