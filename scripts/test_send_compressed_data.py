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
Script which tests sending data to the API using all the supported compression algorithms.
"""

from __future__ import absolute_import
from __future__ import print_function

import copy

import requests

from scalyr_agent.util import SUPPORTED_COMPRESSION_ALGORITHMS
from scalyr_agent.util import COMPRESSION_TYPE_TO_DEFAULT_LEVEL
from scalyr_agent.util import get_compress_and_decompress_func

from benchmarks.micro.utils import generate_add_events_request
from scalyr_agent import compat

SCALYR_TOKEN = compat.os_getenv_unicode("SCALYR_TOKEN")
SCALYR_URL = compat.os_getenv_unicode("SCALYR_URL")

assert SCALYR_TOKEN is not None
assert SCALYR_URL is not None

if not SCALYR_URL.endswith("/addEvents"):
    SCALYR_URL += "/addEvents"

BASE_HEADERS = {
    "Content-Type": "application/json",
}

BASE_BODY = {"token": SCALYR_TOKEN, "session": "session", "threads": []}


def main():
    num_events = 40
    line_length = 200
    attributes_count = 3

    add_events_request = generate_add_events_request(
        num_events=num_events,
        line_length=line_length,
        attributes_count=attributes_count,
        base_body=BASE_BODY,
    )
    add_events_data = add_events_request.get_payload()

    for compression_type in SUPPORTED_COMPRESSION_ALGORITHMS:
        print(("\n" + "=" * 100 + "\n"))
        print(compression_type)

        headers = copy.copy(BASE_HEADERS)
        headers["Content-Encoding"] = compression_type

        compression_level = COMPRESSION_TYPE_TO_DEFAULT_LEVEL[compression_type]
        compress_func, _ = get_compress_and_decompress_func(
            compression_type, compression_level
        )
        data = compress_func(add_events_data)

        assert len(data) < len(add_events_data)

        res = requests.post(SCALYR_URL, headers=headers, data=data)
        print(("Status code: %s" % (res.status_code)))
        print(("Response body: %s" % (res.text)))


if __name__ == "__main__":
    main()
