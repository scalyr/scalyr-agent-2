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


def pytest_addoption(parser):
    parser.addoption(
        "--scalyr-api-key",
        dest="scalyr_api_key",
    )

    parser.addoption(
        "--scalyr-api-read-key",
        dest="scalyr_api_read_key",
    )

    parser.addoption(
        "--scalyr-server", dest="scalyr_server", default="agent.scalyr.com"
    )

    parser.addoption(
        "--test-session-suffix",
        dest="test_session_suffix",
        required=False,
        default=None,
        help="Additional suffix option to make server host or cluster name unique and "
        "to be able to navigate and search through Scalyr logs.",
    )


@pytest.fixture(scope="session")
def config_file():
    """
    Config dist which is read from the 'credentials.json' file.
    """
    config_path = pl.Path(__file__).parent.parent / "credentials.json"
    if not config_path.exists():
        return {}

    return json.loads(config_path.read_text())


def _get_option_value(name: str, config: dict, arg_options, default=None):
    """
    Search for the value with some name in different sources such as command line arguments and config file.
    """

    # First search in command line arguments.
    arg_value = getattr(arg_options, name, None)
    if arg_value:
        return arg_value

    # Then in config file.
    config_value = config.get(name)
    if config_value:
        return config_value

    if default:
        return default

    raise ValueError(f"The option value with name {name} is not set.")


@pytest.fixture(scope="session")
def scalyr_api_key(config_file, request):
    return request.config.option.scalyr_api_key


@pytest.fixture(scope="session")
def scalyr_api_read_key(request):
    return request.config.option.scalyr_api_read_key


@pytest.fixture(scope="session")
def scalyr_server(request):
    return request.config.option.scalyr_server


@pytest.fixture(scope="session")
def test_session_suffix(request):
    return request.config.option.test_session_suffix


@pytest.fixture(scope="session")
def agent_version():
    version_file = SOURCE_ROOT / "VERSION"
    return version_file.read_text().strip()
