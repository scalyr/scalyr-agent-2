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

import logging
import functools
from typing import List

import pytest

from agent_build_refactored.tools import check_output_with_log
from tests.end_to_end_tests.verify import verify_logs
from tests.end_to_end_tests.tools import TimeTracker


log = logging.getLogger(__name__)

pytestmark = [
    # Add timeout for all tests
    pytest.mark.timeout(60 * 1000),
    pytest.mark.usefixtures("dump_info"),
]


def test_basic(
    agent_container_name,
    counter_writer_container_name,
    scalyr_api_key,
    scalyr_api_read_key,
    scalyr_server,
    start_agent_container,
    start_counter_writer_container,
    docker_server_hostname,
    get_agent_log_content,
    image_builder_name,
):
    timeout_tracker = TimeTracker(150)
    start_agent_container(timeout_tracker=timeout_tracker)

    start_counter_writer_container()

    # Quick check for the `scalyr-agent-2-config script.
    export_config_output = check_output_with_log(
        [
            "docker",
            "exec",
            "-i",
            agent_container_name,
            "scalyr-agent-2-config",
            "--export-config",
            "-",
        ],
        description=f"Export config from agent in the container '{agent_container_name}'",
    )
    assert len(export_config_output) > 0

    if "docker-api" in image_builder_name:
        # In case of "docker-api" image type, there is an error message that pops up on each container log line without
        # timestamp, ignore it for now.
        # TODO maybe make this error as warning?
        def ignore_agent_error_predicate(message: str, additional_lines: List[str]):
            if (
                "[monitor:docker_monitor]" in message
                and "No timestamp found on line" in message
            ):
                return True

        # it also seems like the timestamp is implicitly written to the event's message
        # TODO need to check if that is a desired behaviour.
        def counter_getter(e):
            ts, message = e["message"].rstrip("\n").split(" ")
            return int(message)

    else:
        ignore_agent_error_predicate = None
        # Since the test writer pod writes plain text counters, set this count getter.

        def counter_getter(e):
            return int(e["message"].rstrip("\n"))

    log.info("Verify containers logs.")
    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=functools.partial(
            get_agent_log_content, container_name=agent_container_name
        ),
        counter_getter=counter_getter,
        counters_verification_query_filters=[
            f"$containerName=='{counter_writer_container_name}'",
            f"$serverHost=='{docker_server_hostname}'",
        ],
        time_tracker=timeout_tracker,
        ignore_agent_errors_predicates=[ignore_agent_error_predicate],
    )

    logging.info("Test passed!")
