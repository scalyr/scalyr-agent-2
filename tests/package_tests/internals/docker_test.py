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
import logging
import os

from agent_build.tools import constants
from tests.package_tests.internals.common import (
    AgentLogRequestStatsLineCheck,
    AssertAgentLogLineIsNotAnErrorCheck,
    LogVerifier,
)


def build_agent_image(builder_path: pl.Path):
    # Call the image builder script.
    subprocess.check_call(
        [str(builder_path), "--tags", "docker-test"],
    )


def _test(
    image_name: str,
    container_name: str,
    architecture: constants.Architecture,
    scalyr_api_key: str,
):

    logging.info(
        f"Start agent in docker from the image {image_name} in the container {container_name}"
    )

    # Run agent inside the container.
    subprocess.check_call(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            f"SCALYR_API_KEY={scalyr_api_key}",
            "-v",
            "/var/run/docker.sock:/var/scalyr/docker.sock",
            "-v",
            "/var/lib/docker/containers:/var/lib/docker/containers",
            "--platform",
            architecture.as_docker_platform.value,
            image_name,
        ]
    )

    docker_exec_command = [
        "docker",
        "exec",
        "-i",
        container_name,
    ]

    # Pre-create the agent log file so the tail command wont fail before the agent starts.
    subprocess.check_call(
        [*docker_exec_command, "touch", "/var/log/scalyr-agent-2/agent.log"]
    )

    # Execute tail -f command on the agent.log inside the container to read its content.
    agent_log_tail_process = subprocess.Popen(
        [
            *docker_exec_command,
            "tail",
            "-f",
            "-n+1",
            "/var/log/scalyr-agent-2/agent.log",
        ],
        stdout=subprocess.PIPE,
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
        agent_log_tester.add_line_check(
            AgentLogRequestStatsLineCheck(), required_to_pass=True
        )

        # Start agent.log file verification.
        agent_log_tester.verify(timeout=300)

        # TODO: add more checks.
    finally:
        agent_log_tail_process.terminate()

    logging.info("Test passed!")


def run(
    image_name: str,
    architecture: constants.Architecture,
    scalyr_api_key: str,
    name_suffix: str,
):
    """
    :param image_name: Full name of the image to test.
    :param architecture: Architecture of the image to test.
    :param scalyr_api_key: Scalyr API key.
    :param name_suffix: Additional suffix to the agent instance name.
    """

    container_name = f"{image_name}_{architecture.value}_test"

    container_name = f"{container_name}{name_suffix}"

    container_name = container_name.replace(":", "_").replace("/", "_")

    def _delete_agent_container():

        # Kill and remove the previous container, if exists.
        subprocess.check_call(["docker", "rm", "-f", container_name])

    # Cleanup previous test run, if exists.
    _delete_agent_container()

    try:
        _test(
            image_name=image_name,
            container_name=container_name,
            architecture=architecture,
            scalyr_api_key=scalyr_api_key,
        )
    finally:
        _delete_agent_container()
