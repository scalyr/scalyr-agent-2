from pathlib import Path
import shutil

import pytest
import docker
import docker.types
import docker.errors

from tests.tools.agent_verifier import AgentVerifier, CollectorSpawnMatcher, LogMatchCase
from ..tools.agent_runner import BaseAgentContainerRunner

from ..tools.utils import create_temp_dir


def _open(path):
    import os
    os.system("xdg-open {}".format(path))


test_root_dir = str(Path(__file__).parent)

root_dir = str(Path(test_root_dir).parent.parent)

dockerfile_path = Path(test_root_dir, "Dockerfile")


def _clear_docker(docker_client):
    containers = docker_client.containers.list(filters={"name": "scalyr_agent_test*", })
    for container in containers:
        container.remove(force=True)

    docker_client.images.prune(filters={"dangling": True})
    return


@pytest.fixture(scope="session")
def docker_client():
    client = docker.DockerClient()
    _clear_docker(client)
    return client


def build_image(docker_client, path, tag, **kwargs):
    print(f"The '{tag}' image build started.")
    img, build_logs = docker_client.images.build(path=path, tag=f"{tag}", rm=True, **kwargs)
    output = "".join([log.get("stream", "") for log in build_logs])
    print(
        "========================================================\n",
        output,
        "========================================================\n")
    print(f"The '{tag}' image build finished.")
    return img


@pytest.fixture(scope="session")
def package_builder_image(docker_client):
    """Image prepared to produce agent packages within it."""
    build_context_path = str(Path(test_root_dir, "package_builder"))
    img = build_image(docker_client, build_context_path, "scalyr_agent_test_package_builder")
    return img


@pytest.fixture(scope="session")
def rpm_package_path(docker_client, package_builder_image):
    """Create agent rpm package by running container instantiated from 'scalyr_package_builder'"""
    package_directory = create_temp_dir()
    docker_client.containers.run(
        "scalyr_agent_test_package_builder",
        name="scalyr_package_builder",
        mounts=[
            docker.types.Mount("/agent_source", root_dir, type="bind"),
            docker.types.Mount("/package_result", package_directory.name, type="bind")
        ],
        working_dir="/package_result",
        command="python /agent_source/build_package.py rpm",
        auto_remove=True,
    )
    package_path = next(Path(package_directory.name).glob("*.rpm"))
    new_package_path = package_path.parent / "scalyr_agent_package.rpm"
    package_path.rename(new_package_path)

    yield str(new_package_path)
    package_directory.cleanup()


def _build_rpm_image(docker_client, rpm_package_path, python_version="python3"):
    temp_build_context_path = create_temp_dir()

    shutil.copy(
        rpm_package_path,
        Path(temp_build_context_path.name, Path(rpm_package_path).name)
    )

    rpm_dockerfile_path = Path(test_root_dir, "rpm", "Dockerfile")

    shutil.copy(rpm_dockerfile_path, temp_build_context_path.name)

    img = build_image(
        docker_client,
        path=temp_build_context_path.name,
        tag=f"scalyr_agent_test_rpm_{python_version}",
        buildargs={"PYTHON_VERSION": python_version},
    )

    temp_build_context_path.cleanup()

    return img


@pytest.fixture(scope="session")
def agent_rpm_image_python2(docker_client, rpm_package_path):
    img = _build_rpm_image(docker_client, rpm_package_path, python_version="python2")
    return img


@pytest.fixture(scope="session")
def agent_rpm_image_python3(docker_client, rpm_package_path):
    img = _build_rpm_image(docker_client, rpm_package_path, python_version="python3")
    return img


def _agent_container_runner_factory(container_name, image, request):
    test_config = request.getfixturevalue("test_config")
    docker_client = request.getfixturevalue("docker_client")
    agent_config = request.getfixturevalue("agent_config")

    runner = BaseAgentContainerRunner(
        name=container_name,
        image=image,
        docker_client=docker_client,
        test_config=test_config,
        agent_json_config=agent_config
    )
    return runner


@pytest.fixture(scope="session")
def agent_config():
    d = {
        "server_attributes": {
            "serverHost": ""
        },
    }
    return d.copy()


@pytest.fixture(scope="session")
def agent_rpm_python2(agent_rpm_image_python2, request):
    runner = _agent_container_runner_factory(
        "scalyr_agent_test_rpm_smoke_python2",
        agent_rpm_image_python2,
        request
    )
    yield runner

    runner.stop()


@pytest.fixture(scope="session")
def agent_rpm_python3(agent_rpm_image_python3, request):
    runner = _agent_container_runner_factory(
        "scalyr_agent_test_rpm_smoke_python3",
        agent_rpm_image_python3,
        request
    )
    yield runner

    runner.stop()


def test_python3(agent_rpm_python3: BaseAgentContainerRunner, test_config):
    data_json_file = agent_rpm_python3.add_log_file(
        "/var/log/scalyr-agent-2/data.json",
        attributes={"parser": "json"},
        mode="w"
    )

    agent_rpm_python3.run()

    agent_verifier = AgentVerifier(
        test_config["agent_settings"]["SCALYR_SERVER"],
        test_config["agent_settings"]["SCALYR_READ_KEY"],
        test_config["agent_settings"]["HOST_NAME"],
        agent_runner=agent_rpm_python3
    )

    agent_verifier.verify()


def test_python2(agent_rpm_python2: BaseAgentContainerRunner, test_config):
    data_json_file = agent_rpm_python2.add_log_file(
        "/var/log/scalyr-agent-2/data.json",
        attributes={"parser": "json"},
        mode="w"
    )

    agent_rpm_python2.run()

    agent_verifier = AgentVerifier(
        test_config["agent_settings"]["SCALYR_SERVER"],
        test_config["agent_settings"]["SCALYR_READ_KEY"],
        test_config["agent_settings"]["HOST_NAME"],
        agent_runner=agent_rpm_python2
    )

    agent_verifier.verify()
