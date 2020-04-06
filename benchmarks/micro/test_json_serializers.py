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

import json

import six
import pytest

from scalyr_agent.util import set_json_lib
from scalyr_agent.util import get_json_lib
from scalyr_agent.util import json_encode
from scalyr_agent.util import json_decode

from .utils import generate_random_dict

"""
Benchmarks which test JSON serialization and deserialization for various json libraries.
"""


def test_json_json_encode(benchmark):
    _test_json_encode(benchmark, "json")


def test_json_json_decode(benchmark):
    _test_json_decode(benchmark, "json")


def test_ujson_json_encode(benchmark):
    _test_json_encode(benchmark, "ujson")


def test_ujson_json_decode(benchmark):
    _test_json_decode(benchmark, "ujson")


@pytest.mark.skipif(
    not six.PY3, reason="Skipping under Python 2, orjson is only available for Python 3"
)
def test_orjson_json_encode(benchmark):
    _test_json_encode(benchmark, "orjson")


def test_orjson_json_decode(benchmark):
    _test_json_decode(benchmark, "orjson")


def _test_json_encode(benchmark, json_lib):
    set_json_lib(json_lib)

    data = generate_random_dict(keys_count=100)

    def run_benchmark():
        return json_encode(data)

    result = benchmark.pedantic(run_benchmark, iterations=500, rounds=100)

    assert get_json_lib() == json_lib
    assert isinstance(result, six.text_type)
    assert "key_10" in result


def _test_json_decode(benchmark, json_lib):
    set_json_lib(json_lib)

    data = generate_random_dict(keys_count=100)
    data = json.dumps(data)

    def run_benchmark():
        return json_decode(data)

    result = benchmark.pedantic(run_benchmark, iterations=500, rounds=100)

    assert get_json_lib() == json_lib
    assert isinstance(result, dict)
    assert "key_10" in result
