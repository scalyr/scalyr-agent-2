# Copyright 2014-2020 Scalyr Inc.
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


from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import


import json
import logging
import re
import time

if False:
    from typing import Dict
    from typing import List
    from typing import Tuple

import psutil
import pytest

from scalyr_agent import __scalyr__
from tests.utils.agent_runner import AgentRunner


def _perform_workers_check(runner):
    # type: (AgentRunner) -> Tuple[psutil.Process, Dict, List[psutil.Process], List[psutil.Process]]
    worker_session_pids = {}
    agent_children_processes = []  # type: ignore
    workers_processes = []
    status = json.loads(runner.status_json())  # type: ignore

    for worker in status["copying_manager_status"]["workers"]:
        for worker_session in worker["sessions"]:
            worker_session_pids[worker_session["session_id"]] = worker_session["pid"]

    process = psutil.Process(runner.agent_pid)
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


def _stop_and_perform_checks(runner):
    # type: (AgentRunner) -> None

    process, worker_pids, children, workers_processes = _perform_workers_check(
        runner,
    )

    logging.info("Stopping agent.")

    runner.stop()
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


def _check_workers_gracefull_stop(runner, worker_pids, occurrences=1):
    # type: (AgentRunner, Dict, int) -> None
    # check if every worker has logged that it finished.
    for worker_id in worker_pids.keys():
        worker_log_name = "agent-worker-session-{0}.log".format(worker_id)
        worker_log_path = runner.agent_logs_dir_path / worker_log_name  # type: ignore
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


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_agent_kill():
    runner = AgentRunner(
        __scalyr__.InstallType.DEV_INSTALL,
        enable_debug_log=True,
        workers_type="process",
        workers_session_count=2,
    )

    runner.start()
    logging.info("Agent started.")
    time.sleep(1)

    process, worker_pids, children, workers_processes = _perform_workers_check(runner)

    logging.info("All workers are running.")

    logging.info(
        "Killing the agent. All child processes including the worker have to be terminated"
    )

    process.kill()

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

    _check_workers_gracefull_stop(runner, worker_pids)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_agent_stop():
    runner = AgentRunner(
        __scalyr__.InstallType.DEV_INSTALL,
        enable_debug_log=True,
        workers_type="process",
        workers_session_count=2,
    )

    runner.start()
    logging.info("Agent started.")
    time.sleep(1)

    process, worker_pids, children, workers_processes = _perform_workers_check(runner)

    _check_workers_gracefull_stop(runner, worker_pids, occurrences=0)

    _stop_and_perform_checks(runner)

    _check_workers_gracefull_stop(runner, worker_pids, occurrences=1)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_agent_restart():
    runner = AgentRunner(
        __scalyr__.InstallType.DEV_INSTALL,
        enable_debug_log=True,
        workers_type="process",
        workers_session_count=2,
    )

    runner.start()
    logging.info("Agent started.")
    time.sleep(1)

    process, worker_pids, children, workers_processes = _perform_workers_check(runner)

    _check_workers_gracefull_stop(runner, worker_pids, occurrences=0)

    runner.restart()
    time.sleep(1)

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
        runner
    )

    assert process.pid != process2.pid

    _check_workers_gracefull_stop(runner, worker_pids, occurrences=1)

    _stop_and_perform_checks(runner)

    _check_workers_gracefull_stop(runner, worker_pids2, occurrences=2)


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_agent_config_reload():
    runner = AgentRunner(
        __scalyr__.InstallType.DEV_INSTALL,
        enable_debug_log=True,
        workers_type="process",
        workers_session_count=2,
    )

    runner.start()
    logging.info("Agent started.")
    time.sleep(1)

    process, worker_pids, children, workers_processes = _perform_workers_check(runner)

    _check_workers_gracefull_stop(runner, worker_pids, occurrences=0)

    logging.info(
        "Increase the worker count in the config and wait for agent config reload."
    )

    old_worker_pids = worker_pids.copy()
    config = runner.config
    config_worker_count = config["default_sessions_per_worker"]
    config["default_sessions_per_worker"] = config_worker_count + 1
    runner.write_config(config)

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
                runner
            )

            assert process.is_running()
            assert len(workers_processes) == config_worker_count + 1

        except:

            time.sleep(1)
        else:
            break

    _check_workers_gracefull_stop(runner, old_worker_pids, occurrences=1)

    _stop_and_perform_checks(runner)

    _check_workers_gracefull_stop(runner, old_worker_pids, occurrences=2)

    new_workers = {}
    for worker_id, worker_pid in worker_pids.items():
        if worker_id not in old_worker_pids:
            new_workers[worker_id] = worker_pid

    _check_workers_gracefull_stop(runner, new_workers, occurrences=1)
