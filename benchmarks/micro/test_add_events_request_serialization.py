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
Benchmarks which measure performance of the AddEventsRequest serialization (aka serialization
multiple Event objects for single AddEvents API request payload).
"""

from __future__ import absolute_import

import time

import pytest

from .utils import generate_add_events_request


@pytest.mark.submit_result_to_codespeed
def test_serialize_small_add_events_request(benchmark):
    """
    AddEvents request with 40 small events.
    """
    num_events = 40
    line_length = 200
    attributes_count = 3

    add_events_request = generate_add_events_request(
        num_events=num_events,
        line_length=line_length,
        attributes_count=attributes_count,
    )

    def run_benchmark():
        current_time = time.time()
        add_events_request.set_client_time(current_time)
        return add_events_request.get_payload()

    output_bytes = benchmark.pedantic(run_benchmark, iterations=500, rounds=100)
    assert b"thread" in output_bytes
    assert b"attrs" in output_bytes
    assert b"events" in output_bytes
    assert b"message" in output_bytes


@pytest.mark.submit_result_to_codespeed
def test_serialize_medium_add_events_request(benchmark):
    """
    AddEvents request with 30 medium events.
    """
    num_events = 30
    line_length = 2000
    attributes_count = 3

    add_events_request = generate_add_events_request(
        num_events=num_events,
        line_length=line_length,
        attributes_count=attributes_count,
    )

    def run_benchmark():
        current_time = time.time()
        add_events_request.set_client_time(current_time)
        return add_events_request.get_payload()

    output_bytes = benchmark.pedantic(run_benchmark, iterations=500, rounds=100)
    assert b"thread" in output_bytes
    assert b"attrs" in output_bytes
    assert b"events" in output_bytes
    assert b"message" in output_bytes


@pytest.mark.submit_result_to_codespeed
def test_serialize_large_add_events_request(benchmark):
    """
    AddEvents request with 30 large events.
    """
    num_events = 30
    line_length = 50000  # 0.05MB
    attributes_count = 3

    add_events_request = generate_add_events_request(
        num_events=num_events,
        line_length=line_length,
        attributes_count=attributes_count,
    )

    def run_benchmark():
        current_time = time.time()
        add_events_request.set_client_time(current_time)
        return add_events_request.get_payload()

    output_bytes = benchmark.pedantic(run_benchmark, iterations=500, rounds=100)
    assert b"thread" in output_bytes
    assert b"attrs" in output_bytes
    assert b"events" in output_bytes
    assert b"message" in output_bytes
