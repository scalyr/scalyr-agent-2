from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import
import configparser
import os

import pytest
import six

from smoke_tests.tools.compat import Path
from scalyr_agent import compat


def pytest_addoption(parser):
    parser.addoption("--config", action="store")
    parser.addoption("--runner-type", action="store", default="STANDALONE")
    parser.addoption(
        "--package-skip_image_build", action="store", default=False, type=bool
    )
    parser.addoption(
        "--package-image_cache-path", action="store", default=None, type=six.text_type
    )

    parser.addoption(
        "--package-distribution",
        action="append",
        default=[],
        help="list of stringinputs to pass to test functions",
    )

    parser.addoption(
        "--package-python-version",
        action="append",
        default=[],
        help="list of stringinputs to pass to test functions",
    )


def _get_config_value(parser, name, default=None):
    try:
        return parser[name]
    except KeyError:
        return default


def _get_env_or_config_value(env_name, parser, config_name=None):
    env_value = compat.os_getenv_unicode(env_name)
    if env_value:
        return env_value
    return _get_config_value(parser, config_name or env_name)


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
        config = configparser.ConfigParser()
        config.read(config_path)
    else:
        config = dict()

    result_config = dict()

    parser_agent_settings = _get_config_value(config, "agent_settings", default=dict())

    agent_settings = dict()
    for name in agent_env_settings_fields:
        agent_settings[name] = _get_env_or_config_value(name, parser_agent_settings)

    result_config["agent_settings"] = agent_settings

    return result_config


@pytest.fixture(scope="session")
def agent_settings(test_config):
    return test_config["agent_settings"]


@pytest.fixture()
def agent_environment(test_config, agent_env_settings_fields):
    agent_settings = test_config["agent_settings"]
    for name in agent_env_settings_fields:
        env_var_value = agent_settings[name]
        if not env_var_value:
            raise NameError("'{}' environment variable must be specified.".format(name))
        os.environ[name] = env_var_value

    yield

    for name in agent_env_settings_fields:
        del os.environ[name]
