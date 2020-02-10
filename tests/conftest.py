import configparser

import pytest


def pytest_addoption(parser):
    parser.addoption("--config", action="store")


@pytest.fixture(scope="session")
def test_config(request):
    config_path = request.config.getoption("--config")

    config = configparser.ConfigParser()
    config.read(config_path)

    return config