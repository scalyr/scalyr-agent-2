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

import pytest

from scalyr_agent.scalyr_client import Event

from utils import generate_random_dict


@pytest.mark.parametrize("attributes_count", [10, 100, 1000])
@pytest.mark.benchmark(group="add_attributes")
def test_event_add_attributes(benchmark, attributes_count):
    attributes = generate_random_dict(keys_count=attributes_count)

    event = Event(thread_id=100)

    def run_benchmark():
        event.add_attributes(attributes, overwrite_existing=True)

    benchmark.pedantic(run_benchmark, iterations=100, rounds=100)

    output_bytes = event._Event__serialization_base
    assert b"attrs" in output_bytes
