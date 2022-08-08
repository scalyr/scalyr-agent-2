import pathlib as pl
import shutil
from typing import Type

import pytest

from agent_build.tools.common import check_call_with_log, check_output_with_log
from agent_build.package_builders import ContainerImageBuilder, DOCKER_IMAGE_BUILDERS


def pytest_addoption(parser):
    parser.addoption(
        "--image-tarball-path",
        dest="image_tarball_path",
        required=False,
        help="Path to a tarball with the image to test. If not specified, then this tarball wil be built."
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    return request.param


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name) -> Type[ContainerImageBuilder]:
    return DOCKER_IMAGE_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def image_name(image_builder_cls, request, tmp_path_factory):
    """
    Name of the image to tests.
    """

    if request.config.option.image_tarball_path:
        source_image_tarball_path = pl.Path(request.config.option.image_tarball_path)
    else:
        builder = image_builder_cls()
        builder.build()
        source_image_tarball_path = builder.result_image_tarball_path

    tmp_dir = tmp_path_factory.mktemp("image_tarball")

    tarball_path = tmp_dir / source_image_tarball_path.name

    shutil.copy(
        source_image_tarball_path,
        tarball_path
    )

    load_output = check_output_with_log([
        "docker", "load", "-i", str(tarball_path)
    ]).decode().strip()

    image_id = load_output.split(":")[-1]

    image_name = image_builder_cls.get_final_result_image_name()

    check_call_with_log([
        "docker", "tag", image_id, image_name
    ])

    yield image_name

    check_call_with_log([
        "docker", "image", "rm", "-f", image_id, image_name
    ])

# @pytest.fixture(scope="session")
# def image_name22(image_builder_cls, request):
#     """
#     Get name of the ready image to test.
#     """
#
#     reg_container = None
#     # If registry is specified externally, then reuse it.
#     if request.config.option.images_registry:
#         full_image_name = f"{request.config.option.images_registry}/{image_builder_cls.RESULT_IMAGE_NAME}"
#
#     # Registry is not specified, build the image.
#     else:
#         reg_container = LocalRegistryContainer(
#             name="images_registry",
#             registry_port=5050
#         )
#         reg_container.start()
#
#         builder = image_builder_cls(
#             registry=f"localhost:5050",
#             push=True,
#         )
#         builder.build()
#
#         full_image_name = f"localhost:5050/{image_builder_cls.RESULT_IMAGE_NAME}"
#
#     # Pull result image from registry.
#     check_call_with_log(["docker", "pull", full_image_name])
#
#     if reg_container:
#         reg_container.kill()
#
#     check_call_with_log(["docker", "tag", full_image_name, image_builder_cls.RESULT_IMAGE_NAME])
#
#     yield full_image_name
#
#     check_call_with_log(["docker", "image", "rm", image_builder_cls.RESULT_IMAGE_NAME])


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







