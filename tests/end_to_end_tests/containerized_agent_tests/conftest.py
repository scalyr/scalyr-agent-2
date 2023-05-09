import json
import logging
import pathlib as pl
import shutil
import subprocess
from typing import List

import pytest


from  agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import RunnerStep, Runner
from agent_build_refactored.containerized.image_builders import ALL_AGENT_IMAGE_BUILDERS
from tests.end_to_end_tests.containerized_agent_tests.test_image_requirements_builder import (
    TEST_IMAGES_REQUIREMENTS_BUILDERS,
    build_test_image
)


logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--builder-name",
        required=True,
        choices=ALL_AGENT_IMAGE_BUILDERS.keys(),
        help="Name of the builder that build tested agent image"
    )

    parser.addoption(
        "--image-publish-script",
        required=False,
        help="Path to script that publishes image that image builder builds. "
             "If not specified, then publish script is built in place."
    )

    parser.addoption(
        "--coverage-output-file",
        required=False,
        help="If specified, coverage files are retrieved from the tested agent containers and written to this "
             "path as a single combined coverage file",
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    """Name of the builder that build tested packages."""
    return request.config.option.builder_name


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name):
    """
    Builder class that build agent image.
    """
    return ALL_AGENT_IMAGE_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def image_publish_script(image_builder_name, request, tmp_path_factory):
    """
    Path the script that publishes agent image. If not specified, then this script is build in plase.
    """

    if request.config.option.image_publish_script:
        # Publishing script is specified, use it.
        return request.config.option.image_publish_script

    # Build new publishing script.
    image_builder_cls = ALL_AGENT_IMAGE_BUILDERS[image_builder_name]

    image_builder = image_builder_cls()

    image_builder.build()

    tmp_path = tmp_path_factory.mktemp("image_builder_output")
    image_publish_script_path = tmp_path / image_builder.publish_script_path.name
    shutil.copy(
        image_builder.publish_script_path,
        image_publish_script_path
    )

    return image_publish_script_path


IMAGE_REGISTRY_CONTAINER_CONTAINER_PORT = "5000/tcp"


def _start_registry(
        container_name: str
) -> str:
    """
    Start docker container with registry.
    :param container_name: Name of the container.
    :return: Hostname of the started registry
    """
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=True,
    )

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-p",
            f"0:{IMAGE_REGISTRY_CONTAINER_CONTAINER_PORT}",
            "registry:2"
        ],
        check=True,
    )

    # Determine port if the container.
    inspect_result = subprocess.run(
        ["docker", "container", "inspect", container_name],
        check=True,
        capture_output=True
    )

    container_info_json = inspect_result.stdout.decode()

    container_info = json.loads(container_info_json)

    ports_info = container_info[0]["NetworkSettings"]["Ports"]
    host_registry_port = ports_info[IMAGE_REGISTRY_CONTAINER_CONTAINER_PORT][0]["HostPort"]

    return f"localhost:{host_registry_port}"


@pytest.fixture(scope="session")
def prod_image_registry_host():
    """
    Registry that contains production variants of the tested image.
    """
    container_name = "agent_image_prod_image_registry"

    host_registry_host = _start_registry(
        container_name=container_name
    )

    yield host_registry_host

    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=True,
    )


@pytest.fixture(scope="session")
def prod_images(image_publish_script, prod_image_registry_host, tmp_path_factory):
    """
    Name of the prod version of the tested image.
    """
    tmp_path = tmp_path_factory.mktemp("prod_image_build")

    # Publish image to the registry by running publish script.
    # full name of the image, including registry part, has to be written by the script to its output.
    try:
        result = subprocess.run(
            [
                "bash",
                str(image_publish_script),
                "--registry",
                prod_image_registry_host,
                "--tags",
                "test,latest"

            ],
            check=True,
            capture_output=True,
            cwd=tmp_path
        )
    except subprocess.CalledProcessError as e:
        logger.exception(f"Image publishing script has failed.\nStderr:{e.stderr.decode()}")
        raise

    output = result.stdout.decode().strip()
    image_names = output.split("\n")
    return image_names


@pytest.fixture(scope="session")
def test_images_registry_host(prod_images):
    """
    Hostname for the registry that contains test variant of the tested image.
    """
    container_name = "agent_image_test_image_registry"

    # Spin up registry.
    host_registry_host = _start_registry(
        container_name=container_name
    )

    yield host_registry_host

    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=True,
    )


@pytest.fixture(scope="session")
def agent_test_image(
    image_builder_name,
    image_builder_cls,
    prod_images,
    test_images_registry_host,
    tmp_path_factory
):
    """
    Name of the ready test variant of the agent image.
    We need to build a special test variant of the prod image in order to perform additional
    actions during testing. For example test variant has a coverage tool which is needed to measure coverage
    of the agent's code that runs inside the tested container.
    """

    test_image_full_name = build_test_image(
        image_builder_name=image_builder_name,
        prod_image_name=prod_images[0],
        dst_registry_host=test_images_registry_host,
    )
    return test_image_full_name
