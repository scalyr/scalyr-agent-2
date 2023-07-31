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
import pathlib as pl
import json
import time
import datetime
import re
import platform
from typing import List, Dict, Tuple

import pytest
import psutil


from agent_build_refactored.utils.constants import AGENT_VERSION
from tests.end_to_end_tests.tools import TimeoutTracker
from tests.end_to_end_tests.verify import (
    verify_logs,
    write_counter_messages_to_test_log,
    verify_agent_status,
    get_all_events_from_scalyr,
    get_events_page_from_scalyr,
    AgentCommander,
)

logger = logging.getLogger(__name__)


pytestmark = [
    # Make all test cases in this module use these fixtures.
    pytest.mark.usefixtures("shutdown_old_agent_processes", "dump_log"),
]


def test_basic(
    scalyr_api_key,
    scalyr_server,
    scalyr_api_read_key,
    server_host,
    agent_paths,
    agent_commander,
    default_config,
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

    agent_commander.start_and_wait()

    verify_agent_status(
        agent_version=AGENT_VERSION,
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
            messages_count=1000,
            logger=logger,
        ),
        verify_ssl=False,
    )

    agent_commander.stop()


def test_rate_limited(
    scalyr_api_key,
    scalyr_server,
    scalyr_api_read_key,
    server_host,
    agent_paths,
    agent_commander,
    default_config,
):
    """
    Writes 5000 large lines to data.log, then waits until it detects at least one such message in
    Scalyr, then waits a set time before checking how many lines have been uploaded. The intent of this is to test
    rate limiting, and as such the agent must be configured with a rate limiting options.
    """
    upload_test_log_path = agent_paths.logs_dir / "rate_limited_data.log"

    timeout_tracker = TimeoutTracker(200)

    default_config["logs"] = [
        {"path": str(upload_test_log_path), "attributes": {"parser": "json"}}
    ]

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    # This value should match the rate limit configured for the agent when running this test
    rate_limit_bytes_per_second = 500000

    upload_test_log_path.touch()

    agent_commander.start_and_wait(
        logger=logger,
        env={
            "SCALYR_MAX_SEND_RATE_ENFORCEMENT": "500KB/s",
            "SCALYR_DISABLE_MAX_SEND_RATE_ENFORCEMENT_OVERRIDES": "true",
            "SCALYR_MIN_ALLOWED_REQUEST_SIZE": "100",
            "SCALYR_MAX_ALLOWED_REQUEST_SIZE": "500000",
            "SCALYR_MIN_REQUEST_SPACING_INTERVAL": "0.0",
            "SCALYR_MAX_REQUEST_SPACING_INTERVAL": "0.5",
        },
    )

    lines_count = 5000

    start_time = time.time() - 60 * 5

    logger.info("Write test log file messages.")

    verify_agent_status(
        agent_version=AGENT_VERSION,
        agent_commander=agent_commander,
        timeout_tracker=timeout_tracker,
    )

    timestamp = datetime.datetime.utcnow().isoformat()
    message = {
        "count": 0,
        "stream_id": timestamp,
        "filler": "aaajhghjgfijhgfhhjvcfgujhxfgdtyubn vcgfgyuhbnvcgfytuhvbcftyuhjgftyugftyuyygty7u7y8f8ufgfg8fgf8f"
        * 69,
    }

    with upload_test_log_path.open("a") as f:
        for i in range(lines_count):
            message["count"] = i
            json_data = json.dumps(message)
            f.write(json_data)
            f.write("\n")
            f.flush()

    upload_wait_time = 30
    line_size = len(json.dumps(message))

    expected_lines_uploaded = (
        rate_limit_bytes_per_second * (upload_wait_time + 4)
    ) / line_size

    retry_delay = 2

    # Check that any lines have been uploaded, this helps keep the test consistent by working around ingest time.
    while True:
        events = get_events_page_from_scalyr(
            scalyr_server=scalyr_server,
            read_api_key=scalyr_api_read_key,
            start_time=start_time,
            filters=[
                f"$logfile=='{upload_test_log_path}'",
                f"$serverHost=='{server_host}'",
            ],
            timeout_tracker=timeout_tracker,
        )

        if len(events) > 0:
            break

        logger.info("No events, retry.")
        timeout_tracker.sleep(retry_delay)

    logger.info("Successfully verified ingestion has begun.")
    # Give more time for upload and ingestion
    time.sleep(upload_wait_time)

    retry_delay = 5

    while True:
        events = get_all_events_from_scalyr(
            scalyr_server=scalyr_server,
            read_api_key=scalyr_api_read_key,
            start_time=start_time,
            filters=[
                f"$logfile=='{upload_test_log_path}'",
                f"$serverHost=='{server_host}'",
            ],
            timeout_tracker=timeout_tracker,
        )

        events_count = len(events)
        if events_count < expected_lines_uploaded - (expected_lines_uploaded * 0.1):
            logger.info(
                f"Not enough log lines were found (found {events_count}, "
                f"expected {expected_lines_uploaded} +- 10%%)."
            )
            timeout_tracker.sleep(retry_delay, "Can not get enough lines, Give up.")
            continue

        too_many_lines = events_count > expected_lines_uploaded + (
            expected_lines_uploaded * 0.1
        )

        assert not too_many_lines, (
            f"Too many log lines were found (found {events_count}, "
            f"expected {expected_lines_uploaded} +- 10%%)."
        )

        logger.info(
            f"Enough log lines found (found {events_count}, expected {expected_lines_uploaded} +- 10%%)."
        )
        break

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

    logger.info("Starting agent.")
    agent_commander.start()

    assert agent_commander.is_running

    logger.info(
        'Wait until agent crashes because of the fail of the "essential" monitor.'
    )
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

    agent_commander.stop()


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

    logger.info("Starting agent.")
    agent_commander.start()

    assert agent_commander.is_running

    logger.info("Wait until all monitors crash and are not alive in agent's status")
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
            logger.info("All expected monitors are dead.")
            break

        logger.info(
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


def _perform_workers_check(
    agent_commander: AgentCommander,
) -> Tuple[psutil.Process, Dict, List[psutil.Process], List[psutil.Process]]:
    worker_session_pids = {}
    agent_children_processes = []  # type: ignore
    workers_processes = []
    status = agent_commander.get_status_json()  # type: ignore

    for worker in status["copying_manager_status"]["workers"]:
        for worker_session in worker["sessions"]:
            worker_session_pids[worker_session["session_id"]] = worker_session["pid"]

    agent_pid_str = agent_commander.agent_paths.pid_file.read_text().strip()
    agent_pid = int(agent_pid_str)
    process = psutil.Process(int(agent_pid))
    assert process.is_running(), "process is not running"
    agent_children_processes.extend(process.children())

    for wpid in worker_session_pids.values():
        for c in agent_children_processes:
            if wpid == c.pid:
                workers_processes.append(c)
                break
        else:
            pytest.fail(
                "the worker with pid {0} is not found among the agent's child processes.".format(
                    wpid
                )
            )

    for wp in workers_processes:
        assert wp.is_running(), "the agent worker process should being running"

    return process, worker_session_pids, agent_children_processes, workers_processes


def _stop_and_perform_checks(agent_commander: AgentCommander):

    process, worker_pids, children, workers_processes = _perform_workers_check(
        agent_commander=agent_commander,
    )

    logging.info("Stopping agent.")

    agent_commander.stop()
    time.sleep(1)

    logging.info("Checking if all processes have been terminated.")

    assert (
        not process.is_running()
    ), "The agent process should be terminated after stop command"

    for worker in workers_processes:
        assert (
            not worker.is_running()
        ), "the worker processes should be terminated after stop command"

    for child in children:
        assert (
            not child.is_running()
        ), "the child processed should be terminated after stop command"

    logging.info("Agent stopped.")


def _check_workers_gracefull_stop(
    agent_commander: AgentCommander, worker_pids: Dict, occurrences: int = 1
):
    # check if every worker has logged that it finished.
    for worker_id in worker_pids.keys():
        worker_log_name = "agent-worker-session-{0}.log".format(worker_id)
        worker_log_path = agent_commander.agent_paths.logs_dir / worker_log_name  # type: ignore
        assert (
            worker_log_path.exists()
        ), "The log file of the worker '{0}' must exist.".format(worker_id)
        log_content = worker_log_path.read_text()
        found = re.findall(
            r"Worker session '{0}+' is finished".format(worker_id), log_content
        )

        assert (
            len(found) == occurrences
        ), "The message of the graceful stopping should be in log of the worker'{0}' and it should be repeated {1} times".format(
            worker_id, occurrences
        )

    logging.info("All workers are finished gracefully.")


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="Process workers can be enabled only on Linux"
)
@pytest.mark.parametrize(
    ["workers_session_count", "workers_type"],
    [[2, "process"], [1, "process"]],
)
def test_standalone_agent_kill(
    agent_paths,
    agent_commander,
    default_config,
    workers_session_count,
    workers_type,
):

    default_config.update(
        {
            "default_sessions_per_worker": workers_session_count,
            "use_multiprocess_workers": workers_type == "process",
            "disable_send_requests": True,
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    agent_commander.start_and_wait(logger=logger)

    logging.info("Agent started.")

    process, worker_pids, children, workers_processes = _perform_workers_check(
        agent_commander=agent_commander,
    )

    logging.info("All workers are running.")

    logging.info(
        "Killing the agent. All child processes including the worker have to be terminated"
    )

    agent_commander.stop()

    process.wait()

    # loop through all children until all of them are terminated.
    # in case of failure the tests case timeout will be raised.
    while True:
        time.sleep(1)

        # wait more if the agent is not killed yet.
        if process.is_running():
            logging.info("The agent process is still alive.")
            continue

        for child in children:
            if child.is_running():
                logging.info(
                    "The child process with pid {0} is still alive.".format(process.pid)
                )
                break
        else:
            # all child processes are terminated.
            break

    logging.info("All children are terminated.")

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids
    )


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="Process workers can be enabled only on Linux"
)
@pytest.mark.parametrize(
    ["workers_session_count", "workers_type"],
    [[2, "process"], [1, "process"]],
)
def test_standalone_agent_stop(
    agent_paths,
    agent_commander,
    default_config,
    workers_session_count,
    workers_type,
):
    default_config.update(
        {
            "default_sessions_per_worker": workers_session_count,
            "use_multiprocess_workers": workers_type == "process",
            "disable_send_requests": True,
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    agent_commander.start_and_wait(logger=logger)

    logging.info("Agent started.")

    process, worker_pids, children, workers_processes = _perform_workers_check(
        agent_commander=agent_commander
    )

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids, occurrences=0
    )

    _stop_and_perform_checks(agent_commander=agent_commander)

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids, occurrences=1
    )


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="Process workers can be enabled only on Linux"
)
@pytest.mark.parametrize(
    ["workers_session_count", "workers_type"],
    [[2, "process"], [1, "process"]],
)
def test_standalone_agent_restart(
    agent_paths,
    agent_commander,
    default_config,
    workers_session_count,
    workers_type,
):
    default_config.update(
        {
            "default_sessions_per_worker": workers_session_count,
            "use_multiprocess_workers": workers_type == "process",
            "disable_send_requests": True,
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    agent_commander.start_and_wait(logger=logger)

    logging.info("Agent started.")

    process, worker_pids, children, workers_processes = _perform_workers_check(
        agent_commander=agent_commander,
    )

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids, occurrences=0
    )

    agent_commander.restart()

    assert (
        not process.is_running()
    ), "the agent's previous process should terminated after the restart."

    for worker in workers_processes:
        assert (
            not worker.is_running()
        ), "the previous worker processes should be terminated."

    for child in children:
        assert (
            not child.is_running()
        ), "the child processed should be terminated after the restart."

    process2, worker_pids2, children2, workers_processes2 = _perform_workers_check(
        agent_commander=agent_commander,
    )

    assert process.pid != process2.pid

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids, occurrences=1
    )

    _stop_and_perform_checks(
        agent_commander=agent_commander,
    )

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids2, occurrences=2
    )


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="Process workers can be enabled only on Linux"
)
@pytest.mark.parametrize(
    ["workers_session_count", "workers_type"],
    [[2, "process"]],
)
def test_standalone_agent_config_reload(
    agent_paths,
    agent_commander,
    default_config,
    workers_session_count,
    workers_type,
):
    default_config.update(
        {
            "default_sessions_per_worker": workers_session_count,
            "use_multiprocess_workers": workers_type == "process",
            "disable_send_requests": True,
        }
    )

    agent_paths.agent_config_path.write_text(json.dumps(default_config))

    agent_commander.start_and_wait(logger=logger)

    logging.info("Agent started.")

    process, worker_pids, children, workers_processes = _perform_workers_check(
        agent_commander=agent_commander,
    )

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=worker_pids, occurrences=0
    )

    logging.info(
        "Increase the worker count in the config and wait for agent config reload."
    )

    old_worker_pids = worker_pids.copy()
    new_config = default_config.copy()
    config_worker_count = new_config["default_sessions_per_worker"]
    new_config["default_sessions_per_worker"] = config_worker_count + 1
    agent_paths.agent_config_path.write_text(json.dumps(new_config))

    logging.info("checking in the loop until all old worker processes are gone")
    while True:
        assert process.is_running(), "The agent process must not be terminated."

        children_ids = [p.pid for p in process.children()]

        still_running_old_ids = []
        for old_id in old_worker_pids:
            if old_id in children_ids:
                still_running_old_ids.append(old_id)

        if not still_running_old_ids:
            logging.info("All old worker processes are terminated.")
            break

        logging.info(
            "Wait for old worker processes are terminated. Now alive: {0}".format(
                still_running_old_ids
            )
        )
        time.sleep(1)

    time.sleep(1)

    logging.info("checking in loop until the  workers number is increased")
    while True:
        try:
            process, worker_pids, children, workers_processes = _perform_workers_check(
                agent_commander=agent_commander,
            )

            assert process.is_running()
            assert len(workers_processes) == config_worker_count + 1
        except:

            time.sleep(1)
        else:
            break

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=old_worker_pids, occurrences=1
    )

    _stop_and_perform_checks(agent_commander=agent_commander)

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=old_worker_pids, occurrences=2
    )

    new_workers = {}
    for worker_id, worker_pid in worker_pids.items():
        if worker_id not in old_worker_pids:
            new_workers[worker_id] = worker_pid

    _check_workers_gracefull_stop(
        agent_commander=agent_commander, worker_pids=new_workers, occurrences=1
    )
