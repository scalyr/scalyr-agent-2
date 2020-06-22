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
Script which sends notification about finished CodeSpeed agent process level benchmark with
corresponding screenshots to Slack.

As an argument it takes a directory which contains captured screenshots of the corresponding
CodeSpeed graphs.

Sadly Slack incoming webhook integration doesn't allow us to directly send / upload images with the
webhook payload so we first upload screenshots to free and public image hosting service and use
those URLs.
"""

from __future__ import absolute_import
from __future__ import print_function

if False:
    from typing import List
    from typing import Tuple

from io import open

import os
import sys
import glob
import json
import requests

from scalyr_agent import compat

SLACK_CHANNEL = compat.os_getenv_unicode("SLACK_CHANNEL", "#cloud-tech")
SLACK_WEBHOOK = compat.os_getenv_unicode("SLACK_WEBHOOK", None)

CIRCLE_BRANCH = compat.os_getenv_unicode("CIRCLE_BRANCH", "unknown")
CIRCLE_COMMIT = compat.os_getenv_unicode("CIRCLE_SHA1", "unknown")

GITHUB_VIEW_COMMIT_URL = "https://github.com/scalyr/scalyr-agent-2/commit/%s"

if not SLACK_WEBHOOK:
    raise ValueError("SLACK_WEBHOOK environment variable not set")

BASE_PAYLOAD = {
    "channel": SLACK_CHANNEL,
    "attachments": [
        {
            "text": (
                "Agent process Level benchmarks for branch *%s* and commit <%s|%s> have completed.\n\n"
                "Results for most important metrics are available below.\n\n"
                "For more information and details, see "
                "CodeSpeed dashboard (https://scalyr-agent-codespeed.herokuapp.com/timeline/)."
            )
            % (CIRCLE_BRANCH, GITHUB_VIEW_COMMIT_URL % (CIRCLE_COMMIT), CIRCLE_COMMIT)
        }
    ],
}
BASE_HEADERS = {"Content-Type": "application/json"}

IMAGE_SERVICE_URL = "https://0x0.st"


def upload_files(file_paths):
    # type: (List[str]) -> List[Tuple[str, str]]
    """
    Upload provided files and return list of (url, filename) tuples.
    """
    result = []
    for file_path in sorted(file_paths):
        files = {"file": (open(file_path, "rb"))}

        resp = requests.post(IMAGE_SERVICE_URL, files=files)

        if resp.status_code != 200:
            raise Exception("Failed to upload screenshot: %s" % (resp.text))

        result.append((resp.text.strip(), os.path.basename(file_path)))

    return result


def send_notification_to_slack(screenshots_directory):
    # type: (str) -> None
    """
    :param attachments_list: List of tuple where the first item is a screenshot URL and the second
                             one is a description / name of the benchmark.
    """
    screenshots_paths = glob.glob(screenshots_directory + "*.png")
    attachments_list = upload_files(screenshots_paths)

    payload = BASE_PAYLOAD.copy()  # type: dict

    for image_url, image_filename in attachments_list:
        benchmark_name = os.path.splitext(image_filename)[0]
        attachment_item = {
            "type": "image",
            "image_url": image_url,
            "text": "Agent Process Level Benchmark - %s" % (benchmark_name),
        }
        payload["attachments"].append(attachment_item)

    assert SLACK_WEBHOOK is not None
    resp = requests.post(SLACK_WEBHOOK, headers=BASE_HEADERS, data=json.dumps(payload))

    if resp.status_code == 200:
        print("Webhook successfully sent")
    else:
        raise Exception("Failed to send webhook: %s" % (resp.text))


if __name__ == "__main__":
    send_notification_to_slack(screenshots_directory=sys.argv[1])
