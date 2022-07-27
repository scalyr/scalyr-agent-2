import json
import pathlib as pl
import time

import pytest


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
        "--scalyr-server",
        dest="scalyr_server",
        default="agent.scalyr.com"
    )

    parser.addoption(
        "--test-session-name",
        dest="test_session-_ame",
        help="Base name which will go to the 'serverHost' option in the agent config. "
             "It is needed to specify name for server host on normal agent packages test or Kubernetes cluster name "
             "on Kubernetes image test."
    )

    parser.addoption(
        "--test-session-suffix",
        dest="test_session_suffix",
        required=False,
        default=None,
        help="Additional suffix to the '--test-session-name' option to make server host or cluster name unique "
             "to be able to navigate and search through Scalyr logs."
    )


@pytest.fixture(scope="session")
def credentials():
    config_path = pl.Path(__file__).parent.parent / "credentials.json"
    if not config_path.exists():
        return {}

    return json.loads(config_path.read_text())


def _get_option_value(name: str, config: dict, arg_options, default=None):
    arg_value = getattr(arg_options, name, None)
    if arg_value:
        return arg_value

    config_value = config.get(name)
    if config_value:
        return config_value

    if default:
        return default

    raise ValueError(f"The option value with name {name} is not set.")


@pytest.fixture(scope="session")
def scalyr_api_key(credentials, request):
    return _get_option_value(
        name="scalyr_api_key",
        config=credentials,
        arg_options=request.config.option
    )

@pytest.fixture(scope="session")
def scalyr_api_read_key(credentials, request):
    return _get_option_value(
        name="scalyr_api_read_key",
        config=credentials,
        arg_options=request.config.option
    )


@pytest.fixture(scope="session")
def scalyr_server(credentials, request):
    return _get_option_value(
        name="scalyr_server",
        config=credentials,
        arg_options=request.config.option
    )

@pytest.fixture(scope="session")
def test_session_suffix(request, credentials):
    return _get_option_value(
        name="test_session_suffix",
        config=credentials,
        arg_options=request.config.option,
        default=str(int(time.time()))
    )

@pytest.fixture(scope="session")
def test_session_name(credentials, request):
    return _get_option_value(
        name="server_host",
        config=credentials,
        arg_options=request.config.option
    )


@pytest.fixture(scope="session")
def test_session_id(test_session_name, credentials, request):
    suffix = _get_option_value(
        name="test_session_suffix",
        config=credentials,
        arg_options=request.config.option,
        default=str(int(time.time()))
    )

    return f"{test_session_name}-{suffix}"


