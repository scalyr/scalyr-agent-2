# Copyright 2014-2022 Scalyr Inc.
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

import functools
import logging
import os
import pathlib as pl
import json
import shutil
import signal
import subprocess
import sys
import time
from typing import List

import pytest

from tests.end_to_end_tests.tools import AgentPaths, TimeoutTracker
from tests.end_to_end_tests.verify import (
    verify_logs,
    write_counter_messages_to_test_log,
    verify_agent_status,
)
from agent_build_refactored.utils.constants import SOURCE_ROOT

log = logging.getLogger(__name__)


pytestmark = [
    # Make all test cases in this module use these fixtures.
    pytest.mark.usefixtures("shutdown_old_agent_processes", "dump_log"),
]


@pytest.fixture(scope="session")
def agent_paths():
    install_root_path = pl.Path("~/scalyr-agent-dev").expanduser()
    return AgentPaths(
        install_root=install_root_path,
        configs_dir=install_root_path / "config",
        logs_dir=install_root_path / "log",
    )


@pytest.fixture
def server_host(test_session_suffix, request):
    # Make server host unique for each test case
    return f"agent-source-code-e2e-test-{request.node}-{test_session_suffix}"


def _call_agent(cmd_args: List[str]):
    agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
    subprocess.check_call([sys.executable, str(agent_main_path), *cmd_args])


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
    log.info("Stopping remaining agent process...")
    _call_agent(["stop"])

    def pid_exists():
        try:
            os.kill(int(prev_agent_pid), 0)
        except OSError:
            return False
        else:
            return True

    if pid_exists():
        log.info("Stop command didn't help, terminating...")
        os.kill(int(prev_agent_pid), signal.SIGINT)
        time.sleep(3)

    if pid_exists():
        log.info("Terminating also didn't help. Killing.")
        os.kill(int(prev_agent_pid), signal.SIGKILL)
        time.sleep(1)

    if pid_file_path.exists():
        pid_file_path.unlink()


@pytest.fixture
def default_config(scalyr_api_key, server_host):
    return {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": server_host},
        "verify_server_certificate": False,
    }.copy()


@pytest.fixture(scope="session")
def agent_commander(agent_paths):
    from tests.end_to_end_tests.tools import AgentCommander

    agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
    commander = AgentCommander(
        executable_args=[sys.executable, str(agent_main_path)], agent_paths=agent_paths
    )
    return commander


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

    log.info(f"TEST INFO: hostname: {server_host}")

    yield
    if agent_paths.agent_log_path.exists():
        log.info("WHOLE LOG:")
        log.info(agent_paths.agent_log_path.read_text())


def test_basic(
    scalyr_api_key,
    scalyr_server,
    scalyr_api_read_key,
    server_host,
    agent_paths,
    agent_commander,
    default_config,
    agent_version,
):
    """
    Perform some basic checks to running agent.
    Verify agent log for errors, write test messages to a test log file and check if
    those messages are reached the Scalyr server.
    """
    upload_test_log_path = agent_paths.logs_dir / "test.log"

    timeout_tracker = TimeoutTracker(200)

    default_config["logs"] = [
        {"path": str(upload_test_log_path), "attributes": {"parser": "json"}}
    ]

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    agent_commander.start()

    verify_agent_status(
        agent_version=agent_version,
        agent_commander=agent_commander,
        timeout_tracker=timeout_tracker,
    )

    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=agent_paths.agent_log_path.read_text,
        counters_verification_query_filters=[
            f"$logfile=='{upload_test_log_path}'",
            f"$serverHost=='{server_host}'",
        ],
        counter_getter=lambda e: e["attributes"]["count"],
        timeout_tracker=timeout_tracker,
        write_counter_messages=functools.partial(
            write_counter_messages_to_test_log,
            upload_test_log_path=upload_test_log_path,
        ),
        verify_ssl=False,
    )

    agent_commander.stop()


@pytest.mark.timeout(40)
def test_with_failing_essential_monitor(
    scalyr_api_key,
    scalyr_server,
    scalyr_api_read_key,
    server_host,
    agent_paths,
    agent_commander,
    default_config,
):
    """
    Check that special 'stop_agent_on_failure' directive in a monitor's config
    make the whole agent fail if the monitor fails too.
    """
    test_monitors_path = pl.Path(__file__).parent / "fixtures"

    default_config.update(
        {
            "additional_monitor_module_paths": str(test_monitors_path),
            "monitors": [
                {
                    "module": "monitors.essential_failing_monitor",
                    "id": "essential",
                    "stop_agent_on_failure": True,
                }
            ],
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    log.info("Starting agent.")
    agent_commander.start()

    assert agent_commander.is_running

    log.info('Wait until agent crashes because of the fail of the "essential" monitor.')
    while agent_commander.is_running:
        time.sleep(0.1)

    log_content = agent_paths.agent_log_path.read_text()

    assert "Monitor 'essential' is not dead, yet..." in log_content

    assert "Monitor died from due to exception" in log_content
    assert "Exception: Monitor 'essential' bad error." in log_content
    assert "Exception: Monitor 'essential' critical error." in log_content

    assert "Stopping monitor essential_failing_monitor(essential)" in log_content
    assert "Save consolidated checkpoints into file" in log_content
    assert "Copying manager is finished."

    assert (
        "Main run method for agent failed due to exception :stack_trace:" in log_content
    )
    assert (
        "Exception: Monitor 'essential_failing_monitor(essential)' with short hash"
        in log_content
    )
    assert (
        "is not running, stopping the agent because it is configured not to run without this monitor"
        in log_content
    )


@pytest.mark.timeout(40)
def test_with_failing_non_essential_monitors(
    scalyr_api_key,
    scalyr_server,
    scalyr_api_read_key,
    server_host,
    agent_paths,
    agent_commander,
    default_config,
):
    """
    Test the 'stop_agent_on_failure' option is set to False or default.
    Agent, for the backward compatibility reasons, must not fail with those "non-essential" monitors.
    """
    test_monitors_path = pl.Path(__file__).parent / "fixtures"

    default_config.update(
        {
            "additional_monitor_module_paths": str(test_monitors_path),
            "monitors": [
                {
                    "module": "monitors.essential_failing_monitor",
                    "id": "not_essential",
                    "stop_agent_on_failure": False,
                },
                {
                    "module": "monitors.essential_failing_monitor",
                    "id": "not_essential_default",
                },
            ],
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    log.info("Starting agent.")
    agent_commander.start()

    assert agent_commander.is_running

    log.info("Wait until all monitors crash and are not alive in agent's status")
    while True:
        status = agent_commander.get_status_json()
        tracked_monitors = {}
        for ms in status["monitor_manager_status"]["monitors_status"]:
            if ms["monitor_id"] in ["not_essential", "not_essential_default"]:
                tracked_monitors[ms["monitor_id"]] = ms

        assert (
            len(tracked_monitors) == 2
        ), f"Not all required monitors are presented in agent's status. Presented {tracked_monitors}"

        alive_monitors = {
            ms_id: ms for ms_id, ms in tracked_monitors.items() if ms["is_alive"]
        }

        if len(alive_monitors) == 0:
            log.info("All expected monitors are dead.")
            break

        log.info(
            f"Monitors {list(alive_monitors.keys())} are still alive, retry later."
        )
        time.sleep(5)

    log_content = agent_paths.agent_log_path.read_text()

    assert "Monitor 'not_essential' is not dead, yet..." in log_content
    assert "Monitor 'not_essential_default' is not dead, yet..." in log_content

    assert "Monitor died from due to exception" in log_content
    assert "Exception: Monitor 'not_essential' bad error." in log_content
    assert "Exception: Monitor 'not_essential_default' bad error." in log_content
    assert "Exception: Monitor 'not_essential' critical error." in log_content
    assert "Exception: Monitor 'not_essential_default' critical error." in log_content

    # Since those monitors are not "essential", agent won't stop it's work.
    assert agent_commander.is_running

    agent_commander.stop()

    assert not agent_commander.is_running
