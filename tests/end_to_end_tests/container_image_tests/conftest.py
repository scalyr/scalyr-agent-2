import logging
from typing import Type

import pytest

from agent_build.tools.common import check_call_with_log
from agent_build.package_builders import ContainerImageBuilder, DOCKER_IMAGE_BUILDERS
from agent_build.tools.build_in_docker import LocalRegistryContainer


def pytest_addoption(parser):
    parser.addoption(
        "--images-registry",
        dest="images_registry",
        required=False,
        help="Docker images registry URL where image to test is stored."
             "It mainly should be specified on CI/CD tests to get image from existing image registry. "
             'During local testing, this option can be omitted and image and registry will be created "on fly"'
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    return request.param


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name) -> Type[ContainerImageBuilder]:
    return DOCKER_IMAGE_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def image_name(image_builder_cls, request):
    """
    Registry URL from where to get image to test.
    """

    reg_container = None
    # If registry is specified externally, then reuse it.
    if request.config.option.images_registry:
        full_image_name = f"{request.config.option.images_registry}/{image_builder_cls.RESULT_IMAGE_NAME}"

    # Registry is not specified, build the image and put it in the locally created registry.
    else:
        reg_container = LocalRegistryContainer(
            name="images_registry",
            registry_port=5050
        )
        reg_container.start()

        builder = image_builder_cls(
            registry=f"localhost:5050",
            push=True,
        )
        builder.build()

        full_image_name = f"localhost:5050/{image_builder_cls.RESULT_IMAGE_NAME}"

    # Pull result image from registry.
    check_call_with_log(["docker", "pull", full_image_name])

    if reg_container:
        reg_container.kill()

    check_call_with_log(["docker", "tag", full_image_name, image_builder_cls.RESULT_IMAGE_NAME])

    yield full_image_name

    check_call_with_log(["docker", "image", "rm", image_builder_cls.RESULT_IMAGE_NAME])


# @pytest.fixture(scope="session")
# def image_name(image_builder_cls, image_registry):
#
#     full_image_registry_name = f"{image_registry}/{image_builder_cls.RESULT_IMAGE_NAME}"
#
#     # Pull result image from registry.
#     check_call_with_log(["docker", "pull", full_image_registry_name])
#     check_call_with_log(["docker", "tag", full_image_registry_name, image_builder_cls.RESULT_IMAGE_NAME])
#
#     yield image_builder_cls.RESULT_IMAGE_NAME
#
#     check_call_with_log(["docker", "image", "rm", image_builder_cls.RESULT_IMAGE_NAME])
#







