import pathlib as pl
import shutil
from typing import Type

import pytest

from agent_build.tools.common import check_call_with_log, check_output_with_log, LocalRegistryContainer
from agent_build.docker_image_builders import ContainerImageBuilder, DOCKER_IMAGE_BUILDERS


def pytest_addoption(parser):
    parser.addoption(
        "--images-registry",
        dest="images_registry",
        required=False,
        help=""
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
    Registry that contains target image. It may be an externally specified one, or if omitted,
        new local registry with image is created.
    """
    image_main_name = image_builder_cls.get_all_result_image_names()[0]
    # If registry is specified externally, then reuse it.
    if request.config.option.images_registry:
        yield f"{request.config.option.images_registry}/{image_main_name}"

    # Registry is not specified, build the image.
    else:

        with LocalRegistryContainer(
            name="images_registry",
            registry_port=0
        ) as reg_container:

            registry_host = f"localhost:{reg_container.real_registry_port}"

            builder = image_builder_cls(
                registry=registry_host,
                push=True,
            )
            builder.run()

            yield f"{registry_host}/{image_main_name}"


# @pytest.fixture(scope="session")
# def image_name(image_builder_cls, image_registry):
#     """
#     Get name of the ready image to test.
#     """
#
#
#
#
#
#     return full_image_name







