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
Benchmarks which measure performance of the Event class serialization.
"""

from __future__ import absolute_import

from io import BytesIO

import pytest
import six

from scalyr_agent.scalyr_client import Event

from .utils import generate_random_dict
from .utils import generate_random_line


@pytest.mark.submit_result_to_codespeed
# fmt: off
@pytest.mark.parametrize(
    "attributes_count",
    [
        10,
        100,
        1000
    ],
    ids=[
        "10_attributes",
        "100_attributes",
        "1000_attributes",
    ],
)
# fmt: on
@pytest.mark.benchmark(group="add_attributes")
def test_event_add_attributes(benchmark, attributes_count):
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)

    def run_benchmark():
        event.add_attributes(attributes, overwrite_existing=True)

    benchmark.pedantic(run_benchmark, iterations=100, rounds=100)

    output_bytes = event._Event__serialization_base
    assert b"attrs" in output_bytes


@pytest.mark.submit_result_to_codespeed
@pytest.mark.skipif(not six.PY2, reason="Skipping under Python 3")
@pytest.mark.benchmark(group="event_serialize")
def test_serialize_medium_event_stringio(benchmark):
    """
    Event with a medium log line (2000 bytes) and a couple of attributes.

    This benchmark utilizes cStringIO which is only available under Python 2.x and was used
    before the 2.1.1 release.

    This should only serve us as a baseline for some comparisons.
    """
    from cStringIO import StringIO  # pylint: disable=import-error

    line_length = 2000
    attributes_count = 10
    line = generate_random_line(length=line_length)
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)
    event.set_message(line)
    event.add_attributes(attributes)
    output_buffer = StringIO()

    def run_benchmark():
        event.serialize(output_buffer)
        return output_buffer

    result = benchmark.pedantic(run_benchmark, iterations=100, rounds=500)

    output_bytes = result.getvalue()
    assert len(output_bytes) >= line_length
    assert line in output_bytes
    assert "thread" in output_bytes
    assert "attrs" in output_bytes
    assert "message" in output_bytes


@pytest.mark.submit_result_to_codespeed
@pytest.mark.benchmark(group="event_serialize")
def test_serialize_small_event(benchmark):
    """
    Event with a small log line (200 bytes) and a couple of attributes.
    """
    line_length = 200
    attributes_count = 10
    line = generate_random_line(length=line_length)
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)
    event.set_message(line)
    event.add_attributes(attributes)
    output_buffer = BytesIO()

    def run_benchmark():
        event.serialize(output_buffer)
        return output_buffer

    result = benchmark.pedantic(run_benchmark, iterations=100, rounds=500)

    output_bytes = result.getvalue()
    assert len(output_bytes) >= line_length
    assert line in output_bytes
    assert b"thread" in output_bytes
    assert b"attrs" in output_bytes
    assert b"message" in output_bytes


@pytest.mark.submit_result_to_codespeed
@pytest.mark.benchmark(group="event_serialize")
def test_serialize_medium_event(benchmark):
    """
    Event with a medium log line (2000 bytes) and a couple of attributes.
    """
    line_length = 2000
    attributes_count = 5
    line = generate_random_line(length=line_length)
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)
    event.set_message(line)
    event.add_attributes(attributes)
    output_buffer = BytesIO()

    def run_benchmark():
        event.serialize(output_buffer)
        return output_buffer

    result = benchmark.pedantic(run_benchmark, iterations=50, rounds=100)

    output_bytes = result.getvalue()
    assert len(output_bytes) >= line_length
    assert line in output_bytes
    assert b"attrs" in output_bytes
    assert b"thread" in output_bytes
    assert b"message" in output_bytes


@pytest.mark.submit_result_to_codespeed
@pytest.mark.benchmark(group="event_serialize")
def test_serialize_large_event(benchmark):
    """
    Event with a large log line (1 MB) and a couple of attributes.
    """
    line_length = 1000000  # 1 MB
    attributes_count = 5
    line = generate_random_line(length=line_length)
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)
    event.set_message(line)
    event.add_attributes(attributes)
    output_buffer = BytesIO()

    def run_benchmark():
        event.serialize(output_buffer)
        return output_buffer

    result = benchmark.pedantic(run_benchmark, iterations=20, rounds=100)

    output_bytes = result.getvalue()
    assert len(output_bytes) >= line_length
    assert line in output_bytes
    assert b"attrs" in output_bytes
    assert b"thread" in output_bytes
    assert b"message" in output_bytes
