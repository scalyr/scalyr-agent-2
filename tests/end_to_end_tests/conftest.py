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
This is a root conftest for all pytest-based end-to-end tests. And it is mostly responsible for
some common options and fixtures such as Scalyr credentials etc.
"""

import json
import os
import pathlib as pl
import time

import pytest
from _pytest.runner import pytest_runtest_protocol as orig_pytest_runtest_protocol

from agent_build_refactored.utils.constants import SOURCE_ROOT

IN_CICD = os.environ.get("AGENT_BUILD_IN_CICD", False)


def pytest_runtest_protocol(item, nextitem):
    """
    Wrap existing pytest protocol to print special grouping directive that
    makes logs of each test case collapsable on GitHub Actions.
    """
    if IN_CICD:
        print(f"::group::{item.nodeid}")

    orig_pytest_runtest_protocol(item, nextitem)

    if IN_CICD:
        print("::endgroup::")
    return True


def _get_env_var(name: str, default=None):
    value = os.environ.get(name)

    if value is None:
        if default is None:
            raise Exception(f"The environment variable '{name}' has to be specified.")
        return default

    return value


@pytest.fixture(scope="session")
def scalyr_api_key():
    return _get_env_var(name="SCALYR_API_KEY")


@pytest.fixture(scope="session")
def scalyr_api_read_key():
    return _get_env_var(name="READ_API_KEY")


@pytest.fixture(scope="session")
def scalyr_server():
    return _get_env_var(name="SCALYR_SERVER", default="agent.scalyr.com")


@pytest.fixture(scope="session")
def test_session_suffix():
    value = _get_env_var(name="TEST_SESSION_SUFFIX", default="")
    return f"{value}-{int(time.time())}"


@pytest.fixture(scope="session")
def agent_version():
    version_file = SOURCE_ROOT / "VERSION"
    return version_file.read_text().strip()
