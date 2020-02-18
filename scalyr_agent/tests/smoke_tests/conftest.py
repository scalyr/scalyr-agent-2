from __future__ import unicode_literals
from __future__ import print_function

import configparser
import os
import collections

import pytest


def pytest_addoption(parser):
    parser.addoption("--config", action="store")


def _get_config_value(parser, name, default=None):
    try:
        return parser[name]
    except KeyError:
        return default


def _get_env_or_config_value(env_name, parser, config_name=None):
    env_value = os.getenv(env_name)
    if env_value:
        return env_value
    return _get_config_value(parser, config_name or env_name)


@pytest.fixture(scope="session")
def test_config(request):
    config_path = request.config.getoption("--config")
    print(config_path)

    config = configparser.ConfigParser()
    config.read(config_path)

    result_config = dict()

    parser_agent_settings = _get_config_value(config, "agent_settings", default=dict())

    agent_settings_names = [
        "SCALYR_API_KEY",
        "READ_API_KEY",
        "SCALYR_SERVER",
        "AGENT_HOST_NAME",
    ]
    agent_settings = dict()
    for name in agent_settings_names:
        agent_settings[name] = _get_env_or_config_value(name, parser_agent_settings)

    result_config["agent_settings"] = agent_settings

    return result_config


@pytest.fixture(scope="session")
def agent_settings(test_config):
    return test_config["agent_settings"]


@pytest.fixture()
def agent_environment(test_config):
    names = [
        "SCALYR_API_KEY",
        "READ_API_KEY",
        "SCALYR_SERVER",
        "AGENT_HOST_NAME"
    ]

    agent_settings = test_config["agent_settings"]
    for name in names:
        env_var_value = agent_settings[name]
        if not env_var_value:
            raise NameError("'{}' environment variable must be specified.".format(name))
        os.environ[name] = env_var_value

    yield

    for name in names:
        del os.environ[name]
