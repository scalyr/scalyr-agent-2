# Copyright 2014-2023 Scalyr Inc.
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
import logging
import subprocess
from typing import List

logger = logging.getLogger(__name__)


def get_docker_container_host_port(
    container_name: str,
    container_port: str,
    prefix_cmd_args: List[str] = None,
):
    """
    Get a host-side port number of the container.
    """

    prefix_cmd_args = prefix_cmd_args or []

    try:
        inspect_result = subprocess.run(
            [
                *prefix_cmd_args,
                "docker",
                "inspect",
                container_name
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(
            f"The docker inspect command has failed. Stderr: {e.stderr.decode()}"
        )
        raise

    inspect_result = json.loads(
        inspect_result.stdout.decode()
    )
    container_info = inspect_result[0]
    host_port = container_info["NetworkSettings"]["Ports"][container_port][0]["HostPort"]
    return host_port


def delete_container(
    container_name: str,
    force: bool = True,
    initial_cmd_args: List[str] = None,
    logger=None
):
    initial_cmd_args = initial_cmd_args or []

    cmd_args = [
        *initial_cmd_args,
        "docker",
        "rm",
    ]
    if force:
        cmd_args.append("-f")
    try:
        subprocess.run(
            [
                *cmd_args,
                container_name
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        if logger:
            logger.exception(f"Can not remove container '{container_name}'. Stderr: {e.stderr.decode()}")

        raise


