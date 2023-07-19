import pathlib as pl
import subprocess

import pytest

from agent_build_refactored.tools.docker.common import delete_container
from agent_build_refactored.container_images.image_builders import ALL_CONTAINERISED_AGENT_BUILDERS, ImageType, SUPPORTED_ARCHITECTURES



def pytest_addoption(parser):
    parser.addoption(
        "--image-builder-name",
        required=True,
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    parser.addoption(
        "--image-type",
        required=True,
        choices=[t.value for t in ImageType],
    )

    parser.addoption(
        "--image-oci-tarball",
        required=False,
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    return request.config.option.image_builder_name


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name):
    return ALL_CONTAINERISED_AGENT_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def image_type(request):
    return ImageType(request.config.option.image_type)


@pytest.fixture(scope="session")
def registry_with_image():

    container_name = "agent_image_e2e_test_registry"

    delete_container(
        container_name=container_name
    )

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p=5000:5000",
            f"--name={container_name}",
            "registry:2",
        ]
    )

    yield

    delete_container(
        container_name=container_name,
    )

# @pytest.fixture(scope="session")
# def image_full_name():


@pytest.fixture(scope="session")
def image_oci_tarball(image_builder_cls, tmp_path_factory, image_type, request):

    output = tmp_path_factory.mktemp("builder_output")
    output = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2-final/agent_build_output/IMAGE_OCI")
    image_builder = image_builder_cls(
        image_type=image_type,
    )

    tags = image_builder.generate_final_registry_tags(
        registry="localhost:5000",
        user="user",
        tags=["latest", "test"],
    )

    image_builder.publish(
        tags=tags,
        existing_oci_layout_dir=request.config.option.image_oci_tarball
    )

    from tests.end_to_end_tests.container_images_test.tools import build_image_test_dependencies

    subprocess.run(
        [
            "docker",
            "pull",
            tags[0],
        ],
        check=True,
    )
    a=10

    build_image_test_dependencies(
        architectures=SUPPORTED_ARCHITECTURES[:],
        prod_image_name=tags[0],
        output_dir=dependencies_dir,
    )

    a=10



