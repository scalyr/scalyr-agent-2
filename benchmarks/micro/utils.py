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

from __future__ import absolute_import
from io import open

if False:
    from typing import Dict

import os

from six.moves import range

from scalyr_agent.scalyr_client import Event
from scalyr_agent.scalyr_client import AddEventsRequest

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
LOGS_FIXTURES_DIR = os.path.abspath(os.path.join(BASE_DIR, "../fixtures/logs"))


def generate_random_dict(keys_count=10):
    # type: (int) -> Dict[str, str]
    """
    Generate dictionary with random values.
    """
    result = {}

    for index in range(0, keys_count):
        result["key_%s" % (index)] = "value_%s" % (index)

    return result


def generate_random_line(length):
    # type: (int) -> bytes
    """
    Generate random line of the provided length.

    TODO: Support various type of real-life looking log lines (access log, app json log, etc).
    """
    return b"a" * length


def generate_add_events_request(num_events, line_length, attributes_count):
    # type: (int, int, int) -> AddEventsRequest
    """
    Generate AddEventsRequest object with the num_events number of events with the same payload
    payload (line length) size.
    """
    base_body = {"token": "api key", "session": "sessionbar", "threads": []}
    add_events_request = AddEventsRequest(base_body=base_body)

    for index in range(0, num_events):
        line = generate_random_line(length=line_length)
        attributes = generate_random_dict(keys_count=attributes_count)

        event = Event(thread_id=100)
        event.set_message(line)
        event.add_attributes(attributes)

        add_events_request.add_event(event)

    return add_events_request


def read_bytes_from_log_fixture_file(file_name, bytes_to_read):
    # type: (str, int) -> bytes
    """
    Function which reads bytes_to_read from a log ficiture file and "rounding" it to the last
    complete line.
    """
    file_path = os.path.join(LOGS_FIXTURES_DIR, file_name)

    with open(file_path, "rb") as fp:
        data = fp.read(bytes_to_read)

    last_newline_index = data.rfind(b"\n")
    if last_newline_index != len(data):
        data = data[: last_newline_index + 1]

    return data
