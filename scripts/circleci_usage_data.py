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

# See https://circleci.com/pricing/#comparison-table
CREDIT_BUNDLE_PRICE = 15.0
CREDIT_BUNDLE_UNIT_COUNT = 25000.0

# Price for a single CPU usage credit
PRICE_PER_CREDIT = CREDIT_BUNDLE_PRICE / CREDIT_BUNDLE_UNIT_COUNT

GITHUB_API_PRS_URL = "https://api.github.com/repos/{project_slug}/pulls"
GITHUB_API_SEARCH_URL = "https://api.github.com/search/issues"
CIRCLE_CI_API_INSIGHTS_URL = (
    "https://circleci.com/api/v2/insights/{project_slug}/workflows/{workflow}"
)
CIRCLE_CI_WORKFLOW_VIEW_URL = "https://circleci.com/workflow-run/{workflow_id}"

CIRCLE_CI_API_TOKEN = compat.os_environ_unicode.get("CIRCLE_CI_API_TOKEN", None)
MAILGUN_API_TOKEN = compat.os_environ_unicode.get("MAILGUN_API_TOKEN", None)


def get_all_branches_for_repo(project_slug):
    # type: (str) -> List[str]
    """
    Retrieve all the branches (including deleted ones) for a particular repo.

    NOTE: This function utilizes pulls API endpoint since /branches one doesn't include deleted
    branches.
    """
    # 1. Retrieve all the PRs for last week
    url = GITHUB_API_SEARCH_URL.format(project_slug=project_slug)

    now = datetime.datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime(
        "%Y-%m-%d"
    )

    query = "repo:{project_slug} is:pr created:{week_ago}..{now}".format(
        project_slug=project_slug, week_ago=week_ago, now=now
    )
    params = {"q": query, "per_page": "1000", "sort": "created"}

    response = requests.get(url, params=params)
    data = response.json()
    pull_numbers = [item["number"] for item in data["items"]]

    # 2. Retrieve all the branches and filtered ones which haven't been updated during last week
    # (based on the PR activity)
    # 1. Retrieve all the branches
    url = GITHUB_API_PRS_URL.format(project_slug=project_slug)
    params = {"per_page": "100", "sort": "created", "direction": "desc", "state": "all"}
    response = requests.get(url, params=params)
    data = response.json()

    branches = []
    for item in data:
        branch_ref = item.get("head", {}).get("ref", None)
        pull_number = item["number"]

        if not branch_ref or pull_number not in pull_numbers:
            continue

        branches.append(branch_ref)

    return branches


def get_usage_data_for_branch(
    buff, project_slug, workflow, status="success", branch="master", limit=10
):
    # type: (StringIO, str, str, str, str, int) -> None
    """
    Get usage data for the provided project and write it to the provided buffer.
    """
    url = CIRCLE_CI_API_INSIGHTS_URL.format(
        project_slug=project_slug, workflow=workflow
    )
    params = {"limit": "100", "branch": branch}
    headers = {"Circle-Token": CIRCLE_CI_API_TOKEN}

    response = requests.get(url, params=params, headers=headers)

    if response.status_code == 404:
        raise ValueError("Invalid CIRCLE_CI_API_TOKEN or project_slug")

    items = response.json().get("items", [])
    items = [item for item in items if (status == "all" or item["status"] == status)]

    if not items:
        return

    buff.write(
        u'Usage data for recent workflow runs for workflow "%s" with status="%s" and branch "%s"\n\n'
        % (workflow, status, branch)
    )

    count = 0
    for item in items:
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
        branches = get_all_branches_for_repo(
            project_slug=project_slug.replace("gh/", "")
        )
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
        now = datetime.datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime(
            "%Y-%m-%d"
        )

        subject = u"Circle CI Usage Report For Period %s - %s" % (week_ago, now)
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
            "from": "Circle CI Usage Reporter <mailgun@kami.mailgun.org>",
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

    emails = args.emails.split(",") if args.emails else []
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
