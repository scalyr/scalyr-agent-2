import logging
import pytest
import hashlib
import json
import subprocess
from typing import List

from agent_build.tools import check_call_with_log, check_output_with_log
from tests.end_to_end_tests.tools import TimeTracker

log = logging.getLogger(__name__)


@pytest.fixture
def dump_info(docker_server_hostname):
    log.info(f"TEST INFO:\n" f"  server hostname: {docker_server_hostname}")


def _call_docker(cmd_args: List[str]):
    check_call_with_log(["docker", *cmd_args])


@pytest.fixture(scope="session")
def agent_container_name():
    return "scalyr-agent"


@pytest.fixture(scope="session")
def docker_server_hostname(image_builder_name, test_session_suffix, request):
    sha256 = hashlib.sha256()
    sha256.update(request.node.nodeid.encode())
    return f"agent-docker-image-test-{image_builder_name}-{sha256.hexdigest()}-{test_session_suffix}"


@pytest.fixture
def get_agent_log_content():
    """
    Fixture function that reads content of the agent log file in the agent's container.
    """

    def get(container_name: str) -> str:
        return check_output_with_log(
            [
                "docker",
                "exec",
                "-i",
                container_name,
                "cat",
                "/var/log/scalyr-agent-2/agent.log",
            ],
            description=f"Get content of the agent log in the container '{container_name}'.",
        ).decode()

    return get


@pytest.fixture
def start_agent_container(
    image_name,
    agent_container_name,
    scalyr_api_key,
    tmp_path_factory,
    docker_server_hostname,
    image_builder_name,
    get_agent_log_content,
):
    """
    Returns function which starts agent docker container.
    """

    # Kill and remove the previous container, if exists.
    _call_docker(["rm", "-f", agent_container_name])

    extra_config_path = tmp_path_factory.mktemp("extra-config") / "server_host.json"

    extra_config_path.write_text(
        json.dumps({"server_attributes": {"serverHost": docker_server_hostname}})
    )

    def start(timeout_tracker: TimeTracker):
        # Run agent inside the container.

        additional_options = []
        # Add port if that's a syslog type image.
        if "syslog" in image_builder_name:
            additional_options.extend(["-p", "601:601"])

        _call_docker(
            [
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
                *additional_options,
                image_name,
            ]
        )

        with timeout_tracker(20):
            while True:
                try:
                    get_agent_log_content(container_name=agent_container_name)
                    return agent_container_name
                except subprocess.CalledProcessError:
                    timeout_tracker.sleep(5, "Can not read agent's log in time.")

    yield start
    _call_docker(["kill", agent_container_name])
    _call_docker(["rm", agent_container_name])


@pytest.fixture(scope="session")
def counter_writer_container_name():
    return "counter-writer"


@pytest.fixture
def start_counter_writer_container(counter_writer_container_name, image_builder_name):
    """
    Returns function which starts container that writes counter messages, which are needed to verify ingestion
        to Scalyr servers.
    """
    _call_docker(["rm", "-f", counter_writer_container_name])

    def start():

        additional_options = []

        # Add log driver option in case of syslog image type
        if "syslog" in image_builder_name:
            additional_options.extend(
                [
                    "--log-driver",
                    "syslog",
                    "--log-opt",
                    "syslog-address=tcp://127.0.0.1:601",
                ]
            )
        _call_docker(
            [
                "run",
                "-d",
                "--name",
                counter_writer_container_name,
                *additional_options,
                "ubuntu:20.04",
                "bin/bash",
                "-c",
                "for i in {0..999}; do echo $i; done; sleep 10000",
            ]
        )

    yield start
    # cleanup.
    _call_docker(["rm", "-f", counter_writer_container_name])
