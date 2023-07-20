import pathlib as pl
from typing import Callable

import pytest

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.container_images.image_builders import (
    ALL_CONTAINERISED_AGENT_BUILDERS,
    SUPPORTED_ARCHITECTURES,
    ImageType,
)
from tests.end_to_end_tests.container_images_test.tools import build_test_version_of_container_image


_PARENT_DIR = pl.Path(__file__).parent


def add_command_line_args(add_func: Callable):
    add_func(
        "--image-builder-name",
        required=True,
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    add_func(
        "--image_type",
        required=True,
        choices=[t.value for t in ImageType]
    )

    add_func(
        "--architecture",
        required=True,
        choices=[a.value for a in SUPPORTED_ARCHITECTURES]
    )

    add_func(
        "--image-oci-tarball",
        required=False,
    )


def pytest_addoption(parser):
    add_command_line_args(
        add_func=parser.addoption
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    return request.config.option.image_builder_name


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name):
    return ALL_CONTAINERISED_AGENT_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def architecture(request):
    return CpuArch(request.config.option.architecture)


@pytest.fixture(scope="session")
def test_image_tag(image_builder_cls, request):
    image_name = build_test_version_of_container_image(
        image_builder_cls=image_builder_cls,
        ready_image_oci_tarball=request.config.option.image_oci_tarball,
        result_image_name="test",
    )
    yield image_name


