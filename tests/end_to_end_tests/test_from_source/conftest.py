import pathlib as pl
import sys
import shutil
import subprocess
import logging
import os
import time
import signal
from typing import List

import pytest

from agent_build_refactored.utils.constants import SOURCE_ROOT
from tests.end_to_end_tests.tools import AgentPaths, AgentCommander


logger = logging.getLogger(__name__)


def _call_agent(cmd_args: List[str]):
    agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
    subprocess.check_call([sys.executable, str(agent_main_path), *cmd_args])


@pytest.fixture
def shutdown_old_agent_processes(agent_paths, agent_commander):
    """
    Fixture function which start agent.
    """

    # shut down previous test agent (if exists) before recreating the agent's root.
    # We have to do it before the previous agent root and pid file are cleared.
    _shutdown_previous_agent_if_exists(pid_file_path=agent_paths.pid_file)

    if agent_paths.install_root.exists():
        shutil.rmtree(agent_paths.install_root)

    agent_paths.install_root.mkdir(parents=True)
    agent_paths.configs_dir.mkdir()
    agent_paths.logs_dir.mkdir()

    # clear old logs if exists
    for p in agent_paths.logs_dir.glob("*.log"):
        p.unlink()

    yield

    _shutdown_previous_agent_if_exists(pid_file_path=agent_paths.pid_file)


@pytest.fixture
def dump_log(agent_paths, server_host):
    """
    Supporter fixture which dumps agent log after each test.
    """

    logger.info(f"TEST INFO: hostname: {server_host}")

    yield
    if agent_paths.agent_log_path.exists():
        logger.info("WHOLE LOG:")
        logger.info(agent_paths.agent_log_path.read_text())


def _shutdown_previous_agent_if_exists(pid_file_path: pl.Path):
    """
    Tries to detect running agent process from the previously run test and shutdown it.
    :param pid_file_path: Path to the pid file.
    """
    # if no pid file, just return
    if not pid_file_path.exists():
        return

    prev_agent_pid = pid_file_path.read_text().strip()

    # first try stopping it with regular command.
    logger.info("Stopping remaining agent process...")
    _call_agent(["stop"])

    def pid_exists():
        try:
            os.kill(int(prev_agent_pid), 0)
        except OSError:
            return False
        else:
            return True

    if pid_exists():
        logger.info("Stop command didn't help, terminating...")
        os.kill(int(prev_agent_pid), signal.SIGINT)
        time.sleep(3)

    if pid_exists():
        logger.info("Terminating also didn't help. Killing.")
        os.kill(int(prev_agent_pid), signal.SIGKILL)
        time.sleep(1)

    if pid_file_path.exists():
        pid_file_path.unlink()


@pytest.fixture
def server_host(test_session_suffix, request):
    # Make server host unique for each test case
    return f"{request.node.name}-{test_session_suffix}"


@pytest.fixture
def default_config(scalyr_api_key, server_host):
    return {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": server_host},
        "verify_server_certificate": False,
    }.copy()


@pytest.fixture(scope="session")
def agent_paths():
    install_root_path = pl.Path("~/scalyr-agent-dev").expanduser()
    return AgentPaths(
        install_root=install_root_path,
        configs_dir=install_root_path / "config",
        logs_dir=install_root_path / "log",
    )


@pytest.fixture(scope="session")
def agent_commander(agent_paths):

    agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
    commander = AgentCommander(
        executable_args=[sys.executable, str(agent_main_path)], agent_paths=agent_paths
    )
    return commander
