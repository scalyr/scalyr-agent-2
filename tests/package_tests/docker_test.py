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

import argparse
import pathlib as pl
import subprocess
import sys
import time
import datetime
from typing import Union

sys.path.append(str(pl.Path(__file__).absolute().parent.parent.parent))

from tests.package_tests.common import PipeReader, check_agent_log_request_stats_in_line, check_if_line_an_error
from tests.package_tests.common import COMMON_TIMEOUT


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

    # Read lines from agent.log.
    pipe_reader = PipeReader(pipe=agent_log_tail_process.stdout)

    timeout_time = datetime.datetime.now() + datetime.timedelta(seconds=COMMON_TIMEOUT)
    try:
        while True:

            seconds_until_timeout = timeout_time - datetime.datetime.now()
            line = pipe_reader.next_line(timeout=seconds_until_timeout.seconds)
            print(line)
            # Look for any ERROR message.
            check_if_line_an_error(line)

            # TODO: add more checks.

            if check_agent_log_request_stats_in_line(line):
                # The requests status message is found. Stop the loop.
                break
    finally:
        agent_log_tail_process.terminate()

    agent_log_tail_process.communicate()

    print("Test passed!")


def main(
    builder_path: Union[str, pl.Path],
    scalyr_api_key: str
):

    build_agent_image(builder_path)
    _delete_agent_container()

    try:
        _test(scalyr_api_key)
    finally:
        _delete_agent_container()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    main(
        builder_path=args.package_path,
        scalyr_api_key=args.scalyr_api_key
    )