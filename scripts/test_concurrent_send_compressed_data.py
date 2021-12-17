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
Script which tests sending data to the API using the specified compression alrogithm with a specified
concurrency.
"""

from __future__ import absolute_import
from __future__ import print_function

from gevent import monkey
from gevent.pool import Pool
monkey.patch_all()

import copy
import time

import requests

from scalyr_agent.util import SUPPORTED_COMPRESSION_ALGORITHMS
from scalyr_agent.util import COMPRESSION_TYPE_TO_DEFAULT_LEVEL
from scalyr_agent.util import get_compress_and_decompress_func

from benchmarks.micro.utils import generate_add_events_request
from scalyr_agent import compat

SCALYR_TOKEN = compat.os_getenv_unicode("SCALYR_TOKEN")
SCALYR_URL = compat.os_getenv_unicode("SCALYR_URL")

SCRIPT_ALGORITHM = compat.os_getenv_unicode("SCRIPT_ALGORITHM", "zstandard")
SCRIPT_CONCURRENCY = int(compat.os_getenv_unicode("SCRIPT_CONCURRENCY", 10))
SCRIPT_SLEEP_DELAY = int(compat.os_getenv_unicode("SCRIPT_SLEEP_DELAY", 0.1))

assert SCALYR_TOKEN is not None
assert SCALYR_URL is not None

if not SCALYR_URL.endswith("/addEvents"):
    SCALYR_URL += "/addEvents"

BASE_HEADERS = {
    "Content-Type": "application/json",
}

BASE_BODY = {
    "token": SCALYR_TOKEN,
    "session": "test-session",
    "threads": [],
    "sessionInfo": {"test": "yeah", "serverHost": "script-test"}}


def main():
    compression_type = SCRIPT_ALGORITHM
    compression_level = COMPRESSION_TYPE_TO_DEFAULT_LEVEL[compression_type]
    compress_func, _ = get_compress_and_decompress_func(
        compression_type, compression_level
    )

    def send_request(request_id):
        num_events = 1000
        line_length = 1024
        attributes_count = 3

        add_events_request = generate_add_events_request(
            num_events=num_events,
            line_length=line_length,
            attributes_count=attributes_count,
            base_body=BASE_BODY,
            line_prefix=str(request_id),
            include_event_number=True,
        )
        add_events_data = add_events_request.get_payload()

        print(("\n" + "=" * 100 + "\n"))
        print("Request id: %s" % (request_id))
        print("Compression algorithm: %s" % (compression_type))

        headers = copy.copy(BASE_HEADERS)
        headers["Content-Encoding"] = compression_type
        data = compress_func(add_events_data)

        assert len(data) < len(add_events_data)
        print(("Compression ratio: %.2f" % (len(add_events_data) / len (data))))

        res = requests.post(SCALYR_URL, headers=headers, data=data)
        print(("Status code: %s" % (res.status_code)))
        print(("Response body: %s" % (res.text)))

    pool = Pool(SCRIPT_CONCURRENCY)

    request_id = 0

    while True:
        pool.spawn(send_request, request_id)
        time.sleep(SCRIPT_SLEEP_DELAY)
        request_id += 1


if __name__ == "__main__":
    main()
