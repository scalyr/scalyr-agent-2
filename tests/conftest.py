import configparser
import pathlib
import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--config", action="store")


@pytest.fixture(scope="session")
def test_config(request):
    config_path = request.config.getoption("--config")

    # use local 'config.ini' file to configure tests.
    if pathlib.Path(config_path).exists():
        config = configparser.ConfigParser()
        config.read(config_path)
    # use env. variables.
    else:
        config = {
            "agent_settings": {
                "SCALYR_API_KEY": os.getenv("SCALYR_API_KEY"),
                "SCALYR_READ_KEY": os.getenv("SCALYR_READ_KEY"),
                "SCALYR_SERVER": os.getenv("SCALYR_SERVER"),
                "HOST_NAME": os.getenv("HOST_NAME"),
            }
        }

    return config
