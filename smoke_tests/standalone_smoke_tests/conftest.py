from __future__ import absolute_import
import pytest

from smoke_tests.conftest import AGENT_INSTALLATION_TYPES_MAP


def pytest_addoption(parser):
    parser.addoption(
        "--agent-installation-type",
        action="store",
        default="DEV_INSTALL",
        choices=list(AGENT_INSTALLATION_TYPES_MAP.keys()),
        help="The way how agent should be started and which default paths it uses."
        "PACKAGE - assume that the agent has already installed from package and run it according to this."
        "DEV - run agent from source."
        "To learn me, see 'PlatformController' class.",
    )


@pytest.fixture(scope="session")
def agent_installation_type(request):
    """Return corresponding install type from '--agent-installation-type' option."""
    name = request.config.getoption("--agent-installation-type")

    return AGENT_INSTALLATION_TYPES_MAP[name]
