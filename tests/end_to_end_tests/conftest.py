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
import logging
import os
import pathlib as pl
import time
import concurrent.futures
from typing import Callable, List

import pytest
from _pytest.runner import pytest_runtest_protocol as orig_pytest_runtest_protocol

from agent_build.tools.constants import SOURCE_ROOT

IN_CICD = os.environ.get("AGENT_BUILD_IN_CICD", False)

log = logging.getLogger(__name__)


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
    return _get_option_value(
        name="scalyr_api_key", config=config_file, arg_options=request.config.option
    )


@pytest.fixture(scope="session")
def scalyr_api_read_key(config_file, request):
    return _get_option_value(
        name="scalyr_api_read_key",
        config=config_file,
        arg_options=request.config.option,
    )


@pytest.fixture(scope="session")
def scalyr_server(config_file, request):
    return _get_option_value(
        name="scalyr_server", config=config_file, arg_options=request.config.option
    )


@pytest.fixture(scope="session")
def test_session_suffix(request, config_file):
    return _get_option_value(
        name="test_session_suffix",
        config=config_file,
        arg_options=request.config.option,
        default=str(int(time.time())),
    )


@pytest.fixture(scope="session")
def agent_version():
    version_file = SOURCE_ROOT / "VERSION"
    return version_file.read_text().strip()


@pytest.fixture
def collected_agent_logs() -> List[str]:
    """
    List of strings with logs of the agents that were started during current test case.
    When fixture is finalized, it prints all collected logs for debug purposes.
    """
    logs = []
    yield logs

    agent_logs = ""
    for i, agent_log in enumerate(logs):
        agent_logs = f"Agent log from run {i}:\n{agent_log}\n"

    log.info(agent_logs)


@pytest.fixture
def start_collecting_agent_logs(collected_agent_logs):
    """
    Fixture function which accepts "log collector" functions which has to continuously collect agent logs and return
    them at the end. This function will run that collector function in a separate thread and put its result in the
    final collected agent logs fixture.
    """
    executor = concurrent.futures.ThreadPoolExecutor()
    futures = []

    def start_collecting(log_collector_func: Callable[[], str]):
        future = executor.submit(log_collector_func)
        futures.append(future)

    yield start_collecting

    for f in futures:
        result = f.result()
        collected_agent_logs.append(result.decode(errors="replace"))
