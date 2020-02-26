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

from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import
import os

import pytest
import six
import yaml

from smoke_tests.tools.compat import Path


def pytest_addoption(parser):
    parser.addoption("--config", action="store")
    parser.addoption("--runner-type", action="store", default="STANDALONE")
    parser.addoption(
        "--package-image-cache-path", action="store", default=None, type=six.text_type
    )

    parser.addoption(
        "--package-distribution",
        action="append",
        default=[],
        help="list of distribution names for package smoke tests.",
    )

    parser.addoption(
        "--package-python-version",
        action="append",
        default=[],
        help="list of python version for package smoke tests.",
    )


@pytest.fixture(scope="session")
def agent_env_settings_fields():
    return [
        "SCALYR_API_KEY",
        "READ_API_KEY",
        "SCALYR_SERVER",
        "AGENT_HOST_NAME",
    ]


@pytest.fixture(scope="session")
def test_config(request, agent_env_settings_fields):
    config_path = request.config.getoption("--config")
    if config_path and Path(config_path).exists():
        config_path = Path(config_path)
        with config_path.open("r") as f:
            config = yaml.safe_load(f)
    else:
        config = dict()

    return config


@pytest.fixture(scope="session")
def agent_settings(test_config):
    return test_config["agent_settings"]


@pytest.fixture()
def agent_environment(test_config, agent_env_settings_fields):
    """
    Set essential environment variables for each test function and unset the after.
    """
    agent_settings = test_config.get("agent_settings", dict())
    for name in agent_env_settings_fields:
        value = os.environ.get(name, agent_settings.get(name))

        if not value:
            raise NameError("'{0}' environment variable must be specified.".format(name))
        os.environ[name] = value

    yield

    for name in agent_env_settings_fields:
        del os.environ[name]
