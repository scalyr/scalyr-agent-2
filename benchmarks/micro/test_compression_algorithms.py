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

NOTE: We also want to measure CPU utilization for those benchmarks which means we should also run
them using "time.process_time" timer which contains sum of system and user CPU time and not wall
clock time.

This way we get accurate CPU utilization information.
"""

from __future__ import absolute_import
from __future__ import print_function

if False:
    from typing import Tuple
    from typing import Callable

import sys
import zlib
import bz2
import functools

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


from .utils import read_bytes_from_log_fixture_file
from .time_utils import process_time


# fmt: off
@pytest.mark.parametrize("log_tuple",
    [
        ("agent_debug_5_mb.log.gz", 3 * 1024),
        ("agent_debug_5_mb.log.gz", 10 * 1024),
        ("agent_debug_5_mb.log.gz", 500 * 1024),
        ("json_log_5_mb.log.gz", 3 * 1024),
        ("json_log_5_mb.log.gz", 10 * 1024),
        ("json_log_5_mb.log.gz", 500 * 1024),
        ("add_events_request_10_events.log.gz", -1),
        ("add_events_request_100_events.log.gz", -1),
        ("add_events_request_200_events.log.gz", -1),
        ("add_events_request_10_events_with_attributes.log.gz", -1),
        ("add_events_request_100_events_with_attributes.log.gz", -1),
        ("add_events_request_200_events_with_attributes.log.gz", -1),
    ],
    ids=[
        "agent_debug_log_3k",
        "agent_debug_log_10k",
        "agent_debug_log_500k",
        "json_log_3k",
        "json_log_10k",
        "json_log_500k",
        "add_events_10_events",
        "add_events_100_events",
        "add_events_200_events",
        "add_events_10_events_with_attributes",
        "add_events_100_events_with_attributes",
        "add_events_200_events_with_attributes",
    ],
)
# fmt: on
@pytest.mark.parametrize("compression_algorithm_tuple",
    [
        ("deflate", {"level": 3}),
        ("deflate", {"level": 6}),
        ("deflate", {"level": 9}),
        ("bz2", {}),
        ("snappy", {}),
        ("zstandard", {"level": 3}),
        ("zstandard", {"level": 10}),
        ("zstandard", {"level": 12}),
        ("brotli", {"quality": 3}),
        ("brotli", {"quality": 5}),
        ("brotli", {"quality": 8}),
    ],
    ids=[
        "deflate_level_3",
        "deflate_level_6_default",
        "deflate_level_9",
        "bz2",
        "snappy",
        "zstandard_level_3_default",
        "zstandard_level_10",
        "zstandard_level_12",
        "brotli_quality_3",
        "brotli_quality_5",
        "brotli_quality_8",
    ],
)
@pytest.mark.benchmark(group="compress", timer=process_time)
def test_compress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    _test_compress_bytes(benchmark, compression_algorithm_tuple, log_tuple)


# fmt: off
@pytest.mark.parametrize("log_tuple",
    [
        ("agent_debug_5_mb.log.gz", 3 * 1024),
        ("agent_debug_5_mb.log.gz", 10 * 1024),
        ("agent_debug_5_mb.log.gz", 500 * 1024),
        ("json_log_5_mb.log.gz", 3 * 1024),
        ("json_log_5_mb.log.gz", 10 * 1024),
        ("json_log_5_mb.log.gz", 500 * 1024),
    ],
    ids=[
        "agent_debug_log_3k",
        "agent_debug_log_10k",
        "agent_debug_log_500k",
        "json_log_3k",
        "json_log_10k",
        "json_log_500k",
    ],
)
# fmt: on
@pytest.mark.parametrize("compression_algorithm_tuple",
    [
        ("deflate", {"level": 3}),
        ("deflate", {"level": 6}),
        ("deflate", {"level": 9}),
        ("bz2", {}),
        ("snappy", {}),
        ("zstandard", {}),
    ],
    ids=[
        "deflate_level_3",
        "deflate_level_6",
        "deflate_level_9",
        "bz2",
        "snappy",
        "zstandard",
    ],
)
@pytest.mark.benchmark(group="decompress", timer=process_time)
def test_decompress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    _test_decompress_bytes(benchmark, compression_algorithm_tuple, log_tuple)


def _test_compress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    compression_algorithm, kwargs = compression_algorithm_tuple

    file_name, bytes_to_read = log_tuple
    data = read_bytes_from_log_fixture_file(file_name, bytes_to_read)

    compress_func, decompress_func = _get_compress_and_decompress_func(compression_algorithm, kwargs)

    def run_benchmark():
        # Work around for Python <= 3.6 where compress is not a keyword argument, but a regular argument
        if sys.version_info < (3, 6, 0) and compression_algorithm == "deflate":
            result = compress_func(data, kwargs["level"])
        else:
            result = compress_func(data)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=10, rounds=20)

    size_before_compression = len(data)
    size_after_compression = len(result)
    compression_ratio = float(size_before_compression) / size_after_compression

    benchmark.stats.size_before_compression = size_before_compression
    benchmark.stats.size_after_compression = size_after_compression
    benchmark.stats.stats.compression_ratio = compression_ratio

    assert result is not None
    # assert correctness
    assert size_after_compression < size_before_compression
    assert data == decompress_func(result)


def _test_decompress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    compression_algorithm, kwargs = compression_algorithm_tuple

    file_name, bytes_to_read = log_tuple
    data = read_bytes_from_log_fixture_file(file_name, bytes_to_read)

    compress_func, decompress_func = _get_compress_and_decompress_func(compression_algorithm, kwargs)

    compressed_data = compress_func(data)
    assert compressed_data != data

    def run_benchmark():
        result = decompress_func(compressed_data)
        return result

    result = benchmark.pedantic(run_benchmark, iterations=10, rounds=20)

    size_before_decompression = len(compressed_data)
    size_after_decompression = len(result)

    assert result is not None
    # assert correctness
    assert result != compressed_data
    assert size_after_decompression > size_before_decompression
    assert data == result


def _get_compress_and_decompress_func(compression_algorithm, kwargs):
    # type: (str, dict) -> Tuple[Callable, Callable]
    if compression_algorithm == "deflate":
        if sys.version_info < (3, 6, 0):
            # Work around for Python <= 3.6 where compress is not a keyword argument, but a regular
            # argument
            compress_func = zlib.compress  # type: ignore
        else:
            compress_func = functools.partial(zlib.compress, **kwargs)  # type: ignore
        decompress_func = zlib.decompress  # type: ignore
    elif compression_algorithm == "bz2":
        compress_func = functools.partial(bz2.compress, **kwargs)  # type: ignore
        decompress_func = bz2.decompress  # type: ignore
    elif compression_algorithm == "snappy":
        compress_func = functools.partial(snappy.compress, **kwargs)  # type: ignore
        decompress_func = snappy.decompress  # type: ignore
    elif compression_algorithm == "zstandard":
        compressor = zstandard.ZstdCompressor(**kwargs)
        decompressor = zstandard.ZstdDecompressor()
        compress_func = compressor.compress  # type: ignore
        decompress_func = decompressor.decompress  # type: ignore
    elif compression_algorithm == "brotli":
        compress_func = functools.partial(brotli.compress, **kwargs)  # type: ignore
        decompress_func = brotli.decompress  # type: ignore
    else:
        raise ValueError("Unsupported algorithm: %s" % (compression_algorithm))

    return compress_func, decompress_func
