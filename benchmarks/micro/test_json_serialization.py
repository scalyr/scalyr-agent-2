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

import six
import pytest

from scalyr_agent.util import set_json_lib
from scalyr_agent.util import get_json_lib
from scalyr_agent.util import json_encode
from scalyr_agent.util import json_decode
import scalyr_agent.util

from utils import generate_random_dict


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
