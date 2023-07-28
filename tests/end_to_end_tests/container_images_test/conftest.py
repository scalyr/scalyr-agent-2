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


import pathlib as pl

import pytest

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.container_images import ALL_CONTAINERISED_AGENT_BUILDERS
from agent_build_refactored.container_images.image_builders import (
    ImageType,
)
from tests.end_to_end_tests.container_images_test.tools import (
    build_test_version_of_container_image,
    add_command_line_args,
)


def pytest_addoption(parser):
    add_command_line_args(add_func=parser.addoption)


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
def test_image_name(
    image_type,
    image_builder_name,
    image_builder_cls,
    request,
):
    """
    Fixture which prepares test version of the image.
    :return:
    """
    if request.config.option.image_oci_tarball:
        ready_image_oci_tarball = pl.Path(request.config.option.image_oci_tarball)
    else:
        ready_image_oci_tarball = None

    image_name = f"agent_test_image_{image_builder_name}"
    build_test_version_of_container_image(
        image_type=image_type,
        image_builder_cls=image_builder_cls,
        architecture=CpuArch(request.config.option.architecture),
        result_image_name=image_name,
        ready_image_oci_tarball=ready_image_oci_tarball,
        install_additional_test_libs=not request.config.option.do_not_install_additional_test_libs,
    )

    return image_name
