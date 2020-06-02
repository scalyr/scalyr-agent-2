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
Script which verifies that /addEvents API endpoint returns correct response headers in different
scenarios.
"""

from __future__ import absolute_import
from __future__ import print_function

if False:
    from typing import List

import json

import requests

from scalyr_agent import compat

# A list of headers names which should be present in the response for a specific response status
# code. If either more or less headers are returned, the script will fail.
EXPECTED_HEADER_NAMES_401 = [
    "Server",
    "Date",
    "Content-Type",
    "Content-Length",
    "Connection",
]

EXPECTED_HEADER_NAMES_200 = [
    "Server",
    "Date",
    "Content-Type",
    "Content-Length",
    "Cache-Control",
    "Connection",
]

# List of API urls to test
API_URLS = [
    # Prod US
    "https://scalyr.com/addEvents",
    "https://www.scalyr.com/addEvents",
    "https://agent.scalyr.com/addEvents",
    # Prod EU
    "https://eu.scalyr.com/addEvents",
    "https://upload.eu.scalyr.com/addEvents",
]

SCALYR_TOKEN_PROD_US = compat.os_getenv_unicode("SCALYR_TOKEN_PROD_US")
SCALYR_TOKEN_PROD_EU = compat.os_getenv_unicode("SCALYR_TOKEN_PROD_EU")

if not SCALYR_TOKEN_PROD_US:
    raise ValueError("SCALYR_TOKEN_PROD_US environment variable not set")

if not SCALYR_TOKEN_PROD_EU:
    raise ValueError("SCALYR_TOKEN_PROD_EU environment variable not set")


BASE_HEADERS = {
    "Content-Type": "application/json",
}
BASE_BODY = {"session": "session", "threads": [], "events": []}


def verify_api_response_headers_and_status_code(
    url, data, expected_status_code, expected_headers
):
    # type: (str, str, int, List[str]) -> None
    """
    Verify that the POST request to the provided URL with the provided data returns expected status
    code and response headers.
    """
    resp = requests.post(url=url, headers=BASE_HEADERS, data=data)

    if resp.status_code != expected_status_code:
        raise ValueError(
            "Expected %s status code, got %s" % (expected_status_code, resp.status_code)
        )

    actual_header_names = list(resp.headers.keys())

    if set(actual_header_names) != set(expected_headers):
        raise ValueError(
            "Expected the following header keys: %s, got: %s"
            % (", ".join(expected_headers), ", ".join(actual_header_names))
        )

    print("API endpoint %s returned correct headers" % (url))


def main():
    for url in API_URLS:
        if "eu" in url:
            # prod eu
            token = compat.os_getenv_unicode("SCALYR_TOKEN_PROD_EU")
        else:
            # prod us
            token = compat.os_getenv_unicode("SCALYR_TOKEN_PROD_US")

        # 1. Test unauthenticated scenario (aka invalid / missing API key)
        print("Unauthenticated checks (expecting status code 401)")
        print("")
        verify_api_response_headers_and_status_code(
            url=url,
            data="{}",
            expected_status_code=401,
            expected_headers=EXPECTED_HEADER_NAMES_401,
        )

        # 2. Test authenticated scenario with a valid API key and invalid payload
        print("Authenticated checks (expecting status code 400)")
        print("")
        data = BASE_BODY.copy()
        data["token"] = token
        del data["events"]
        del data["session"]
        verify_api_response_headers_and_status_code(
            url=url,
            data=json.dumps(data),
            expected_status_code=400,
            expected_headers=EXPECTED_HEADER_NAMES_401,
        )

        # 2. Test authenticated scenario with a valid API key and valid payload
        print("Authenticated checks (expecting status code 200)")
        print("")
        data = BASE_BODY.copy()
        data["token"] = token
        verify_api_response_headers_and_status_code(
            url=url,
            data=json.dumps(data),
            expected_status_code=200,
            expected_headers=EXPECTED_HEADER_NAMES_200,
        )


if __name__ == "__main__":
    main()
