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

import pytest

from scalyr_agent.util import get_compress_and_decompress_func


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
@pytest.mark.parametrize(
    "compression_algorithm_tuple",
    [
        ("deflate", 3),
        ("deflate", 6),
        ("deflate", 9),
        ("bz2", 9),
        ("snappy", None),
        ("zstandard", 3),
        ("zstandard", 5),
        ("zstandard", 10),
        ("zstandard", 12),
        ("brotli", 3),
        ("brotli", 5),
        ("brotli", 8),
        ("lz4", 0),
        ("lz4", 3),
        ("lz4", 16),
    ],
    ids=[
        "deflate_level_3",
        "deflate_level_6_default",
        "deflate_level_9",
        "bz2_level_6_default",
        "snappy",
        "zstandard_level_3_default",
        "zstandard_level_5",
        "zstandard_level_10",
        "zstandard_level_12",
        "brotli_quality_3",
        "brotli_quality_5",
        "brotli_quality_8",
        "lz4_level_0_default",
        "lz4_level_3",
        "lz4_level_16",
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
@pytest.mark.parametrize("compression_algorithm_tuple",
    [
        ("deflate", 3),
        ("deflate", 6),
        ("deflate", 9),
        ("bz2", 9),
        ("snappy", None),
        ("zstandard", 3),
        ("zstandard", 5),
        ("zstandard", 10),
        ("zstandard", 12),
        ("brotli", 3),
        ("brotli", 5),
        ("brotli", 8),
        ("lz4", 0),
        ("lz4", 3),
        ("lz4", 16),
    ],
    ids=[
        "deflate_level_3",
        "deflate_level_6_default",
        "deflate_level_9",
        "bz2_level_6_default",
        "snappy",
        "zstandard_level_3_default",
        "zstandard_level_5",
        "zstandard_level_10",
        "zstandard_level_12",
        "brotli_quality_3",
        "brotli_quality_5",
        "brotli_quality_8",
        "lz4_level_0_default",
        "lz4_level_3",
        "lz4_level_16",
    ],
)
# fmt: on
@pytest.mark.benchmark(group="decompress", timer=process_time)
def test_decompress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    _test_decompress_bytes(benchmark, compression_algorithm_tuple, log_tuple)


def _test_compress_bytes(benchmark, compression_algorithm_tuple, log_tuple):
    compression_algorithm, compression_level = compression_algorithm_tuple

    file_name, bytes_to_read = log_tuple
    data = read_bytes_from_log_fixture_file(file_name, bytes_to_read)

    compress_func, decompress_func = get_compress_and_decompress_func(
        compression_algorithm, compression_level
    )

    def run_benchmark():
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
    compression_algorithm, compression_level = compression_algorithm_tuple

    file_name, bytes_to_read = log_tuple
    data = read_bytes_from_log_fixture_file(file_name, bytes_to_read)

    compress_func, _ = get_compress_and_decompress_func(compression_algorithm, compression_level)

    compressed_data = compress_func(data)
    assert compressed_data != data

    # NOTE: We intentionally request new decompression function so we get new zstandard context for
    # decompression (this way we avoid dictionary being already populated).
    _, decompress_func = get_compress_and_decompress_func(
        compression_algorithm, compression_level
    )

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
