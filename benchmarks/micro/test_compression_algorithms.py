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
Benchmarks which compare various compression algorithms.

TODO:

    - Record compression ratio
    - Record CPU utilization
    - Use more realistic log like data
"""

from __future__ import absolute_import
from __future__ import print_function

import json
import zlib
import bz2

import pytest

try:
    import snappy
except ImportError:
    snappy = None

try:
    import zstandard
except ImportError:
    zstandard = None

try:
    import brotli
except ImportError:
    brotli = None


from .utils import generate_random_dict


def test_deflate_compress_small_json_string(benchmark):
    data = generate_random_dict(keys_count=100)
    data = json.dumps(data).encode("utf-8")

    _test_compress_string(benchmark, data, "deflate")


def test_bz2_compress_small_json_string(benchmark):
    data = generate_random_dict(keys_count=100)
    data = json.dumps(data).encode("utf-8")

    _test_compress_string(benchmark, data, "bz2")


@pytest.mark.skipif(not snappy, reason="python-snappy library not available")
def test_snappy_compress_small_json_string(benchmark):
    data = generate_random_dict(keys_count=100)
    data = json.dumps(data).encode("utf-8")

    _test_compress_string(benchmark, data, "snappy")


@pytest.mark.skipif(not zstandard, reason="zstandard library not available")
def test_zstandard_compress_small_json_string(benchmark):
    data = generate_random_dict(keys_count=100)
    data = json.dumps(data).encode("utf-8")

    _test_compress_string(benchmark, data, "zstandard")


@pytest.mark.skipif(not brotli, reason="brotli library not available")
def test_brotli_compress_small_json_string(benchmark):
    data = generate_random_dict(keys_count=10)
    data = json.dumps(data).encode("utf-8")

    _test_compress_string(benchmark, data, "brotli")


def _test_compress_string(benchmark, data, compression_algorithm):
    def run_benchmark():
        if compression_algorithm == "deflate":
            result = zlib.compress(data)
        elif compression_algorithm == "bz2":
            result = bz2.compress(data)
        elif compression_algorithm == "snappy":
            result = snappy.compress(data)
        elif compression_algorithm == "zstandard":
            cctx = zstandard.ZstdCompressor()
            result = cctx.compress(data)
        elif compression_algorithm == "brotli":
            result = brotli.compress(data)
        else:
            raise ValueError("Unsupported algorithm: %s" % (compression_algorithm))
        return result

    result = benchmark.pedantic(run_benchmark, iterations=200, rounds=100)

    size_before_compression = len(data)
    size_after_compression = len(result)
    compression_ratio = size_before_compression / size_after_compression

    # TODO: Store that in result file
    print(size_before_compression)
    print(size_after_compression)
    print(compression_ratio)

    assert result is not None
    assert size_after_compression < size_before_compression
