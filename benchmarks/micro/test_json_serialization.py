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
Benchmarks which test JSON serialization and deserialization with various json libraries.
"""

from __future__ import absolute_import

import json

import six
import pytest

from scalyr_agent.util import set_json_lib
from scalyr_agent.util import get_json_lib
from scalyr_agent.util import json_encode
from scalyr_agent.util import json_decode
import scalyr_agent.util

from .utils import generate_random_dict
from .utils import read_bytes_from_log_fixture_file

# We cache some data to avoid loading it for each test. Keep in mind that actual "setup" / loading
# phase is not included in the actual benchmarking timing data.
CACHED_TEST_DATA = {
    "encode": {},
    "decode": {},
}  # type: dict


@pytest.mark.parametrize("sort_keys", [False, True], ids=["no_sort_keys", "sort_keys"])
@pytest.mark.parametrize("keys_count", [10, 100, 1000])
@pytest.mark.parametrize("json_lib", ["json", "ujson", "orjson"])
@pytest.mark.benchmark(group="json_encode")
def test_json_encode_with_custom_options(benchmark, json_lib, keys_count, sort_keys):
    # NOTE: orjson doesn't support sort_keys=True
    if json_lib == "orjson":
        if not six.PY3:
            pytest.skip(
                "Skipping under Python 2, orjson is only available for Python 3"
            )
        elif sort_keys is True:
            pytest.skip("orjson doesn't support sort_keys=True")

    set_json_lib(json_lib)
    scalyr_agent.util.SORT_KEYS = sort_keys

    data = generate_random_dict(keys_count=keys_count)

    def run_benchmark():
        return json_encode(data)

    result = benchmark.pedantic(run_benchmark, iterations=50, rounds=100)

    assert get_json_lib() == json_lib
    assert scalyr_agent.util.SORT_KEYS == sort_keys
    assert isinstance(result, six.text_type)
    assert json_decode(result) == data


# fmt: off
@pytest.mark.parametrize("log_tuple",
    [
        ("agent_debug_5_mb.log.gz", 3 * 1024),
        ("agent_debug_5_mb.log.gz", 500 * 1024),
    ],
    ids=[
        "agent_debug_log_3k",
        "agent_debug_log_500k",
    ],
)
# fmt: on
@pytest.mark.parametrize("json_lib", ["json", "ujson", "orjson"])
@pytest.mark.benchmark(group="json_encode")
def test_json_encode(benchmark, json_lib, log_tuple):
    if not six.PY3 and json_lib == "orjson":
        pytest.skip("Skipping under Python 2, orjson is only available for Python 3")
        return

    _test_json_encode(benchmark, json_lib, log_tuple)


# fmt: off
@pytest.mark.parametrize("log_tuple",
    [
        ("json_log_5_mb.log.gz", 3 * 1024),
        ("json_log_5_mb.log.gz", 500 * 1024),
    ],
    ids=[
        "json_log_3k",
        "json_log_500k",
    ],
)
# fmt: on
@pytest.mark.parametrize("json_lib", ["json", "ujson", "orjson"])
@pytest.mark.benchmark(group="json_decode")
def test_json_decode(benchmark, json_lib, log_tuple):
    if not six.PY3 and json_lib == "orjson":
        pytest.skip("Skipping under Python 2, orjson is only available for Python 3")
        return

    _test_json_decode(benchmark, json_lib, log_tuple)


def _test_json_encode(benchmark, json_lib, log_tuple):
    """
    :param json_lib: JSON library to use.
    :param log_tuple: Tuple with (log_filename, log_bytes_to_use).
    """
    set_json_lib(json_lib)

    file_name, bytes_to_read = log_tuple

    if log_tuple not in CACHED_TEST_DATA["encode"]:
        data = read_bytes_from_log_fixture_file(file_name, bytes_to_read)
        data = six.ensure_text(data)

        CACHED_TEST_DATA["encode"][log_tuple] = data

    data = CACHED_TEST_DATA["encode"][log_tuple]

    def run_benchmark():
        return json_encode(data)

    result = benchmark.pedantic(run_benchmark, iterations=20, rounds=50)

    assert get_json_lib() == json_lib
    assert isinstance(result, six.text_type)
    # assert json.dumps(data) == result


def _test_json_decode(benchmark, json_lib, log_tuple):
    """
    :param json_lib: JSON library to use.
    :param log_tuple: Tuple with (log_filename, log_bytes_to_use).
    """
    set_json_lib(json_lib)

    file_name, bytes_to_read = log_tuple

    if log_tuple not in CACHED_TEST_DATA["decode"]:
        data = read_bytes_from_log_fixture_file(file_name, bytes_to_read).strip()
        obj = {"lines": []}
        for line in data.split(b"\n"):
            line_decoded = json.loads(six.ensure_text(line))
            obj["lines"].append(line_decoded)

        data = json.dumps(obj)

        CACHED_TEST_DATA["decode"][log_tuple] = six.ensure_text(data)

    data = CACHED_TEST_DATA["decode"][log_tuple]

    def run_benchmark():
        return json_decode(data)

    result = benchmark.pedantic(run_benchmark, iterations=20, rounds=50)

    assert get_json_lib() == json_lib
    assert isinstance(result, dict)
    # assert json.loads(result) == data
