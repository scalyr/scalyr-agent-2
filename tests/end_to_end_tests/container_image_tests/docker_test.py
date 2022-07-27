#!/usr/bin/env python3
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


import json
import pathlib as pl
import subprocess
import logging
import functools
import os
import time
from typing import List

import pytest

from agent_build.tools import constants
from agent_build.tools.common import check_call_with_log, check_output_with_log
from tests.end_to_end_tests.tools import get_testing_logger
from tests.end_to_end_tests.log_verify import verify_logs


log = get_testing_logger(__name__)


def pytest_generate_tests(metafunc):
    """
    parametrize test case according to which image has to be tested.
    """
    image_builder_name = metafunc.config.getoption("image_builder_name")
    metafunc.parametrize(
        ["image_builder_cls"], [[image_builder_name]], indirect=True
    )


def _call_docker(cmd_args: List[str]):
    check_call_with_log(["docker", *cmd_args])


def build_agent_image(builder_path: pl.Path):
    # Call the image builder script.
    subprocess.check_call(
        [str(builder_path), "--tags", "docker-test"],
    )


@pytest.fixture(scope="session")
def agent_container_name():
    return "scalyr-agent"

@pytest.fixture(scope="session")
def docker_server_hostname(image_name, test_session_suffix):
    return f"{image_name}-test-{test_session_suffix}"



@pytest.fixture(scope="session")
def start_agent_container(agent_container_name, scalyr_api_key,full_image_name, tmp_path_factory, docker_server_hostname):
    """
    Returns function which starts agent docker container.
    """

    # Kill and remove the previous container, if exists.
    _call_docker(["rm", "-f", agent_container_name])

    extra_config_path = tmp_path_factory.mktemp("extra-config") / "server_host.json"

    extra_config_path.write_text(
        json.dumps({
            "server_attributes": {
                "serverHost": docker_server_hostname
            }
        })
    )

    def start():
        # Run agent inside the container.
        _call_docker([
            "run",
            "-d",
            "--name",
            agent_container_name,
            "-e",
            f"SCALYR_API_KEY={scalyr_api_key}",
            "-v",
            "/var/run/docker.sock:/var/scalyr/docker.sock",
            "-v",
            "/var/lib/docker/containers:/var/lib/docker/containers",
            # mount extra config
            "-v",
            f"{extra_config_path}:/etc/scalyr-agent-2/agent.d/{extra_config_path.name}",
            # "--platform",
            # architecture.as_docker_platform.value,
            full_image_name,
        ])

    yield start
    _call_docker(["kill", agent_container_name])
    _call_docker(["rm", agent_container_name])


@pytest.fixture(scope="session")
def counter_writer_container_name():
    return "counter-writer"


@pytest.fixture(scope="session")
def start_counter_writer_container(counter_writer_container_name):
    """
    Returns function which starts container that writes counter messages, which are needed to verify ingestion
        to Scalyr servers.
    """
    _call_docker(["rm", "-f", counter_writer_container_name])


    def start():
        _call_docker([
            "run",
            "-d",
            "--name",
            counter_writer_container_name,
            "ubuntu:20.04",
            "bin/bash",
            "-c",
            "for i in {0..999}; do echo $i; done; sleep 10000"
        ])

    yield start
    # cleanup.
    _call_docker(["rm", "-f", counter_writer_container_name])


def _get_agent_log_content(container_name: str) -> str:
    """
    Read content of the agent log file in the agent's container.
    """
    return check_output_with_log([
        "docker",
        "exec",
        "-i",
        container_name,
        "cat",
        "/var/log/scalyr-agent-2/agent.log"
    ]).decode()


def test(
    agent_image,
    full_image_name,
    agent_container_name,
    counter_writer_container_name,
    scalyr_api_key,
    scalyr_api_read_key,
    scalyr_server,
    start_agent_container,
    start_counter_writer_container,
    docker_server_hostname
):

    log.info(f"Starting test. Scalyr logs can be found by the host name: {docker_server_hostname}")
    start_agent_container()

    # Wait a little
    time.sleep(5)

    start_counter_writer_container()

    time.sleep(5)

    # Pre-create the agent log file so the tail command wont fail before the agent starts.
    _call_docker(
        ["exec", "-i", agent_container_name, "touch", "/var/log/scalyr-agent-2/agent.log"]
    )

    # Quick check for the `scalyr-agent-2-config script.
    export_config_output = subprocess.check_output(
        ["docker", "exec", "-i", agent_container_name, "scalyr-agent-2-config", "--export-config", "-"]
    )
    assert len(export_config_output) > 0

    log.info("Verify containers logs.")
    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=functools.partial(_get_agent_log_content, container_name=agent_container_name),
        # Since the test writer pod writes plain text counters, set this count getter.
        counter_getter=lambda e: int(e["message"].rstrip("\n")),
        counters_verification_query_filters=[
            f"$containerName=='{counter_writer_container_name}'",
            f"$serverHost=='{docker_server_hostname}'"
        ],
    )

    logging.info("Test passed!")
