# Copyright 2014-2022 Scalyr Inc.
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
This script performs set of simple sanity checks for a venv that is installed with Agent.
"""
import os
import re
import argparse

from agent_build_refactored.managed_packages.scalyr_agent_python3 import PYTHON_PACKAGE_SSL_VERSION

parser = argparse.ArgumentParser()
parser.add_argument(
    "--including-binary-packages",
    action="store_true",
)
args = parser.parse_args()


print("Check uuid")
import uuid

assert (
    str(uuid.uuid5(uuid.NAMESPACE_URL, "www.example.com"))
    == "b63cdfa4-3df9-568e-97ae-006c5b8fd652"
)


compression_test_data = b"""\
Donec rhoncus quis sapien sit amet molestie. Fusce scelerisque vel augue
nec ullamcorper. Nam rutrum pretium placerat. Aliquam vel tristique lorem,
sit amet cursus ante. In interdum laoreet mi, sit amet ultrices purus
pulvinar a. Nam gravida euismod magna, non varius justo tincidunt feugiat.
Aliquam pharetra lacus non risus vehicula rutrum. Maecenas aliquam leo
felis. Pellentesque semper nunc sit amet nibh ullamcorper, ac elementum
dolor luctus. Curabitur lacinia mi ornare consectetur vestibulum."""

print("Check bz2")
import bz2

compressed = bz2.compress(compression_test_data)
uncompressed = bz2.decompress(compressed)
assert uncompressed == compression_test_data


print("Check zlib")
import zlib

compressed = zlib.compress(compression_test_data)
uncompressed = zlib.decompress(compressed)
assert uncompressed == compression_test_data

print("Check lzma")
import lzma

compressed = lzma.compress(compression_test_data)
uncompressed = lzma.decompress(compressed)
assert uncompressed == compression_test_data

print("Check ctypes")
from ctypes.util import find_library

assert find_library("c") == "libc.so.6"

print("Check requests")
import requests

with requests.Session() as s:
    resp = s.get("https://example.com")

assert (
    "This domain is for use in illustrative examples in documents."
    in resp.content.decode()
)


# Since we may run package tests with using "frozen" pytest runner, it is important to check
# that the interpreter from tested package does not interfere with anything from that frozen test runner.
# For example, we can try to import some library that is presented in test runner but not in the package.
try:
    import pytest  # NOQA

    raise Exception("Pytest module must not be presented in the tested package.")
except ModuleNotFoundError:
    pass


if not args.including_binary_packages:
    exit(0)

print("Check OpenSSL")
import ssl

escaped_open_ssl_version = re.escape(PYTHON_PACKAGE_SSL_VERSION)
assert re.match(
    rf"OpenSSL {escaped_open_ssl_version}\s+\d+ [A-Za-z]+ \d+", ssl.OPENSSL_VERSION
), f"Current version of OpenSSL does not match expected {PYTHON_PACKAGE_SSL_VERSION}"


print("Check orjson")
import orjson

data = orjson.dumps({"1": "2"})
assert orjson.loads(data) == {"1": "2"}

print("Check zstandard")
import zstandard

compressed = zstandard.compress(compression_test_data)
uncompressed = zstandard.decompress(compressed)
assert uncompressed == compression_test_data

print("Check lz4")
import lz4.frame

compressed = lz4.frame.compress(compression_test_data)
uncompressed = lz4.frame.decompress(compressed)
assert uncompressed == compression_test_data

