import configparser
import pathlib
import os
import collections

import pytest


def pytest_addoption(parser):
    parser.addoption("--config", action="store")


class InfiniteDict(collections.defaultdict):
    def __init__(self):
        super(InfiniteDict, self).__init__(self.__class__)


def _get_config_value(parser, name):
    try:
        return parser[name]
    except KeyError:
        return None


def _get_env_or_config_value(env_name, parser, config_name=None):
    env_value = os.getenv(env_name)
    if env_value:
        return env_value
    return _get_config_value(parser, config_name or env_name)


@pytest.fixture(scope="session")
def test_config(request):
    config_path = request.config.getoption("--config")

    config = configparser.ConfigParser()
    config.read(config_path)

    result_config = dict()

    parser_agent_settings = _get_config_value(config, "agent_settings")

    agent_settings_names = [
        "SCALYR_API_KEY",
        "SCALYR_READ_KEY",
        "SCALYR_SERVER",
        "SCALYR_TEST_HOST_NAME",
    ]
    agent_settings = dict()
    for name in agent_settings_names:
        agent_settings[name] = _get_env_or_config_value(name, parser_agent_settings)

    result_config["agent_settings"] = agent_settings

    return result_config


@pytest.fixture()
def agent_environment(test_config):
    names = [
        "SCALYR_API_KEY",
        "SCALYR_READ_KEY",
        "SCALYR_SERVER",
        "SCALYR_TEST_HOST_NAME"
    ]

    agent_settings = test_config["agent_settings"]
    for name in names:
        os.environ[name] = agent_settings[name]

    yield

    for name in names:
        del os.environ[name]
