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

import os
import time
from io import open
import json
import pathlib as pl

import six

from scalyr_agent import compat
from scalyr_agent import __scalyr__
from tests.smoke_tests.verifier import (
    AgentLogVerifier,
    DataJsonVerifier,
    DataJsonVerifierRateLimited,
    SystemMetricsVerifier,
    ProcessMetricsVerifier,
    AgentWorkerSessionLogVerifier,
)
from tests.utils.agent_runner import AgentRunner

# This has to be a DEV installation so we can use install root as source root
_SOURCE_ROOT = __scalyr__.get_install_root()

_AGENT_PACKAGE_PATH = pl.Path(_SOURCE_ROOT, "scalyr_agent")


def _create_data_json_file(runner, data_json_verifier):
    # NOTE: It's important that the file exists before starting the agent otherwise it won't be
    # consumed by the agent and the tests will fail.
    agent_logs_dir_path = six.text_type(runner.agent_logs_dir_path)
    data_log_path = six.text_type(data_json_verifier._data_json_log_path)

    if os.path.exists(data_log_path):
        os.remove(data_log_path)

    try:
        os.makedirs(agent_logs_dir_path)
    except OSError:
        pass

    with open(data_log_path, "a") as _:
        pass


def _test_standalone_smoke(
    agent_installation_type,
    python_version=None,
    rate_limited=False,
    workers_type="thread",
    workers_sessions_count=1,
):
    """
    Agent standalone test to run within the same machine.
    """
    if agent_installation_type == __scalyr__.InstallType.DEV_INSTALL:
        os.chdir(_AGENT_PACKAGE_PATH)

    print("Agent host name: {0}".format(compat.os_environ_unicode["AGENT_HOST_NAME"]))

    runner = AgentRunner(
        agent_installation_type,
        enable_debug_log=True,
        workers_type=workers_type,
        workers_session_count=workers_sessions_count,
    )

    if python_version:
        runner.switch_version(python_version)

    agent_log_verifier = AgentLogVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )
    worker_sessions_verifier = None

    if workers_type == "process":
        worker_sessions_verifier = AgentWorkerSessionLogVerifier(
            runner, compat.os_environ_unicode["SCALYR_SERVER"]
        )

    if rate_limited:
        data_json_verifier = DataJsonVerifierRateLimited(
            runner, compat.os_environ_unicode["SCALYR_SERVER"]
        )
    else:
        data_json_verifier = DataJsonVerifier(
            runner, compat.os_environ_unicode["SCALYR_SERVER"]
        )
    system_metrics_verifier = SystemMetricsVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )
    process_metrics_verifier = ProcessMetricsVerifier(
        runner, compat.os_environ_unicode["SCALYR_SERVER"]
    )

    _create_data_json_file(runner=runner, data_json_verifier=data_json_verifier)

    runner.start()

    time.sleep(1)

    print("Verify 'agent.log'")
    assert agent_log_verifier.verify(), "Verification of the file: 'agent.log' failed"

    if workers_type == "process":
        # if workers are multiprocess, then we check if worker session logs are ingested.
        print("Verify worker sessions log files.")
        assert (
            worker_sessions_verifier.verify()
        ), "Verification of the worker session log files is failed"

    print("Verify 'linux_system_metrics.log'")
    assert (
        system_metrics_verifier.verify()
    ), "Verification of the file: 'linux_system_metrics.log' failed"
    print("Verify 'linux_process_metrics.log'")
    assert (
        process_metrics_verifier.verify()
    ), "Verification of the file: 'linux_process_metrics.log' failed"

    assert data_json_verifier.verify(), "Verification of the file: 'data.json' failed"

    if workers_type == "process":
        # increase worker sessions count, restart and also check if all worker logs are ingested.
        config = runner.config
        sessions_count = config["default_sessions_per_worker"]
        sessions_count += 1

        worker_sessions_verifier = AgentWorkerSessionLogVerifier(
            runner, compat.os_environ_unicode["SCALYR_SERVER"]
        )

        config["default_sessions_per_worker"] = sessions_count
        runner.write_config(config)
        runner.restart()

        agent_status = json.loads(runner.status_json())
        assert (
            len(agent_status["copying_manager_status"]["workers"][-1]["sessions"])
            == sessions_count
        )

        print("Verify worker sessions log files.")

        assert (
            worker_sessions_verifier.verify()
        ), "Verification of the worker session log files is failed"

    runner.stop()
