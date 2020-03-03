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

import pytest  # type: ignore
import yaml

from scalyr_agent.__scalyr__ import DEV_INSTALL, PACKAGE_INSTALL
from scalyr_agent import compat
from smoke_tests.tools.compat import Path

# mapping of PlatformController 'install_type' constants
# to possible values of the '--agent-installation-type' command line options.
AGENT_INSTALLATION_TYPES_MAP = {
    "PACKAGE_INSTALL": PACKAGE_INSTALL,
    "DEV_INSTALL": DEV_INSTALL,
}


def pytest_addoption(parser):
    parser.addoption(
        "--test-config",
        action="store",
        default=Path(__file__).parent / "config.yml",
        help="Path to yaml file with essential agent settings and another test related settings. "
        "Fields from this config file will be set as environment variables.",
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
    """
    load config file as dict if it is located in project root and its path specified in pytest command line.
    If it is not specified, return empty dict.
    """
    config_path = request.config.getoption("--test-config")
    if config_path and Path(config_path).exists():
        config_path = Path(config_path)
        with config_path.open("r") as f:
            config = yaml.safe_load(f)
    else:
        config = dict()

    return config


@pytest.fixture()
def agent_environment(test_config, agent_env_settings_fields):
    """
    Set essential environment variables for test function and unset the after.
    """
    agent_settings = test_config.get("agent_settings", dict())
    for name in agent_env_settings_fields:
        value = compat.os_environ_unicode.get(name, agent_settings.get(name))

        if not value:
            raise NameError(
                "'{0}' environment variable must be specified.".format(name)
            )
        os.environ[name] = value

    yield

    for name in agent_env_settings_fields:
        del os.environ[name]
