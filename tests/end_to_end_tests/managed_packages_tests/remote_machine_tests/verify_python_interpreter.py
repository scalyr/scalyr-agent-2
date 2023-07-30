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
This script performs set of simple sanity checks for a Python interpreter that is shipped by the
Linux dependency packages.
"""

import sys
import pathlib as pl
import site

from agent_build_refactored.utils.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.managed_packages_builders import (
    AGENT_SUBDIR_NAME as SUBDIR,
)

# Make sure that current interpreter prefixes are withing subdirectories.
assert sys.prefix == f"/var/opt/{SUBDIR}/venv"
assert sys.exec_prefix == sys.prefix

# Check that only verified prefixes are used.
assert set(site.PREFIXES) == {sys.prefix, sys.exec_prefix}

PYTHON_MAJOR_VERSION = sys.version_info[0]
PYTHON_MINOR_VERSION = sys.version_info[1]
PYTHON_X_Y_VERSION = f"{PYTHON_MAJOR_VERSION}.{PYTHON_MINOR_VERSION}"

# Verify that site packages paths collection consists only of expected paths.
assert set(site.getsitepackages()) == {
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
    f"{sys.exec_prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
}

# Verify that only previously checked prefixes are used in the Python paths.
assert sys.path == [
    str(pl.Path(__file__).parent),
    str(SOURCE_ROOT),
    f"{sys.base_prefix}/lib/python{PYTHON_MAJOR_VERSION}{PYTHON_MINOR_VERSION}.zip",
    f"{sys.base_prefix}/lib/python{PYTHON_X_Y_VERSION}",
    f"{sys.base_prefix}/lib/python{PYTHON_X_Y_VERSION}/lib-dynload",
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
]

print("Check OpenSSL")
import ssl  # noqa

import hashlib

sha256 = hashlib.sha256()
sha256.update("123456789".encode())
assert (
    sha256.hexdigest()
    == "15e2b0d3c33891ebb0f1ef609ec419420c20e320ce94c65fbc8c3312448eb225"
)

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

print("Check requests")
import requests

with requests.Session() as s:
    resp = s.get("https://example.com")

assert (
    "This domain is for use in illustrative examples in documents."
    in resp.content.decode()
)

# This is just installed by the tests as an additional requirement to test it out.
import flask  # noqa


# Since we may run package tests with using "frozen" pytest runner, it is important to check
# that the interpreter from tested package does not interfere with anything from that frozen test runner.
# For example, we can try to import some library that is presented in test runner but not in the package.
try:
    import pytest  # NOQA

    raise Exception("Pytest module must not be presented in the tested package.")
except ModuleNotFoundError:
    pass
