#!/usr/bin/env python3
# Copyright 2014-2021 Scalyr Inc.
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

import pathlib as pl
import subprocess
import time
import logging
import os
from typing import Union

from tests.package_tests.common import AgentLogRequestStatsLineCheck, AssertAgentLogLineIsNotAnErrorCheck, LogVerifier


def build_agent_image(builder_path: pl.Path):
    # Call the image builder script.
    subprocess.check_call(
        [str(builder_path), "--tags", "docker-test"],
    )


_AGENT_CONTAINER_NAME = "scalyr-agent-docker-test"


def _delete_agent_container():

    # Kill and remove the previous container, if exists.
    subprocess.check_call(
        ["docker", "rm", "-f", _AGENT_CONTAINER_NAME]
    )


def _test(scalyr_api_key: str):

    # Run agent inside the container.
    subprocess.check_call(
        [
            "docker", "run", "-d", "--name", _AGENT_CONTAINER_NAME, "-e", f"SCALYR_API_KEY={scalyr_api_key}",
            "-v", "/var/run/docker.sock:/var/scalyr/docker.sock", "scalyr/scalyr-agent-docker-json:docker-test"
        ]
    )

    # Wait a little.
    time.sleep(3)

    # Execute tail -f command on the agent.log inside the container to read its content.
    agent_log_tail_process = subprocess.Popen(
        ["docker", "exec", "-i", _AGENT_CONTAINER_NAME, "tail", "-f", "-n+1", "/var/log/scalyr-agent-2/agent.log"],
        stdout=subprocess.PIPE
    )

    # Read lines from agent.log. Create pipe reader to read lines from the previously created tail process.

    # Also set the mode for the process' std descriptor as non-blocking.
    os.set_blocking(agent_log_tail_process.stdout.fileno(), False)

    try:
        logging.info("Start verifying the agent.log file.")
        # Create verifier object for the agent.log file.
        agent_log_tester = LogVerifier()

        # set the 'read' method of the 'stdout' pipe of the previously created tail process as a "content getter" for
        # the log verifier, so it can fetch new data from the pipe when it is available.
        agent_log_tester.set_new_content_getter(agent_log_tail_process.stdout.read)

        # Add check for any ERROR messages to the verifier.
        agent_log_tester.add_line_check(AssertAgentLogLineIsNotAnErrorCheck())
        # Add check for the request stats message.
        agent_log_tester.add_line_check(AgentLogRequestStatsLineCheck(), required_to_pass=True)

        # Start agent.log file verification.
        agent_log_tester.verify(timeout=300)

        # TODO: add more checks.
    finally:
        agent_log_tail_process.terminate()

    logging.info("Test passed!")


def run(
    builder_path: Union[str, pl.Path],
    scalyr_api_key: str
):

    build_agent_image(builder_path)
    _delete_agent_container()

    try:
        _test(scalyr_api_key)
    finally:
        _delete_agent_container()
