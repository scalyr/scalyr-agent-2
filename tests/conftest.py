import os
import shutil
import tempfile

import pytest
import yaml

from scalyr_agent import compat
from tests.utils.compat import Path
from tests.utils.common import TEMP_PREFIX


@pytest.fixture(scope="session", autouse=True)
def clear_tmp():
    for child in Path(tempfile.gettempdir()).iterdir():
        if child.name.startswith(TEMP_PREFIX):
            if child.is_dir():
                shutil.rmtree(str(child))
            else:
                os.remove(str(child))




def pytest_addoption(parser):
    parser.addoption(
        "--test-config",
        action="store",
        default=Path(__file__).parent / "config.yml",
        help="Path to yaml file with essential agent settings and another test related settings. "
             "Fields from this config file will be set as environment variables.",
    )

    parser.addoption(
        "--no-dockerize",
        action="store_true",
        help="run slow tests"
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

    # NOTE: We don't need environment variables at the end since setup runs before
    # each test which means environment would only be correctly set up for a single test
    # In our case each tox invocation results in multiple tests since we use
    # pytest_generate_tests functionality.
