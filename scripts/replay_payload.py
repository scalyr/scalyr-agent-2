#!/usr/bin/env python
# Copyright 2014-2021 Scalyr Inc.
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
Script which replays the provided payload in JSON format to the provided API endpoint.

Example usage:

     SCALYR_WRITE_TOKEN="..." SCALYR_READ_TOKEN="..." SCALYR_URL="https://app/addEvents" ./replay_payload.py \
         --path payload.json [--reset-timestamps] [--add-request-id]

NOTE: If you want to make it easier to search for those requests you should use --add-request-id
flag which will add random request id to session attributes which you can use to filter on those
events.

Keep in mind that you may not always want to use that since changing the payload may affect the
behavior (same as using --reset-timestamps).
"""

from __future__ import absolute_import
from __future__ import print_function

from typing import List

import sys
import copy
import json
import uuid
import datetime
import argparse
import time

from pprint import pprint
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.parse import quote_plus

import requests

from scalyr_agent import compat

SCALYR_TOKEN = compat.os_getenv_unicode("SCALYR_TOKEN")
SCALYR_WRITE_TOKEN = compat.os_getenv_unicode("SCALYR_WRITE_TOKEN")
SCALYR_READ_TOKEN = compat.os_getenv_unicode("SCALYR_READ_TOKEN")
SCALYR_URL = compat.os_getenv_unicode("SCALYR_URL")

assert SCALYR_WRITE_TOKEN is not None
assert SCALYR_URL is not None

if not SCALYR_URL.endswith("/addEvents"):
    SCALYR_URL += "/addEvents"

BASE_HEADERS = {
    "Content-Type": "application/json",
}


def reset_payload_timestamps(payload: dict):
    start_dt = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    start_ts_s = int(datetime.datetime.timestamp(start_dt))

    for event in payload.get("events", []):
        ts_s = start_ts_s + 1
        ts_ns = int(ts_s * 1000000000)
        event["ts"] = ts_ns

    return payload


def get_query_url(
    scalyr_url: str, params: dict = None, filters: List[str] = None
) -> str:
    params = params or {}
    parsed_url = urlparse(SCALYR_URL)

    url = "%s://%s/api/query?queryType=log" % (parsed_url.scheme, parsed_url.netloc)

    if params:
        url += "&%s" % (urlencode(params))

    if filters:
        url += "&filter=%s" % ("+and+".join(filters))

    return url


def main(
    path: str,
    reset_timestamps: bool = False,
    add_request_id: bool = False,
    query: bool = False,
) -> None:
    with open(path, "r") as fp:
        content = fp.read()

    payload = json.loads(content)

    if reset_timestamps:
        payload = reset_payload_timestamps(payload)
    request_id = None
    if add_request_id:
        request_id = str(uuid.uuid4())
        payload["sessionInfo"]["requestId"] = request_id

    print("Will send payload:")
    pprint(payload)

    if request_id:
        print("Using request id: %s" % (request_id))

    headers = copy.copy(BASE_HEADERS)
    payload["token"] = SCALYR_WRITE_TOKEN

    res = requests.post(SCALYR_URL, headers=headers, data=json.dumps(payload))
    print(("Status code: %s" % (res.status_code)))
    print(("Response body: %s" % (res.text)))

    if query:
        time.sleep(5)

        print("Search data")
        filter_value = "requestId==%s" % (quote_plus('"%s"' % (request_id)))
        params = {
            "maxCount": 100,
            "startTime": "12h",
            "token": SCALYR_READ_TOKEN,
        }
        filters = [filter_value]
        query_url = get_query_url(scalyr_url=SCALYR_URL, params=params, filters=filters)
        print(query_url)

        res = requests.get(query_url)
        print("Status code: %s" % (res.status_code))
        print("Response body")
        pprint(res.json())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=("Replay provided addEvents payload in JSON format")
    )

    parser.add_argument(
        "--path",
        help=("Path to a JSON file with captured payload to replay."),
        required=True,
    )

    parser.add_argument(
        "--reset-timestamps",
        help=("True to reset timestamps."),
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--add-request-id",
        help=("True to add random request id to session attributes."),
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--query",
        help=("True to search for logs after ingestion."),
        action="store_true",
        default=False,
    )

    args = parser.parse_args(sys.argv[1:])

    main(
        path=args.path,
        reset_timestamps=args.reset_timestamps,
        add_request_id=args.add_request_id,
        query=args.query,
    )
