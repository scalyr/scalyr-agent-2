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

"""
This script builds testable version of the agent container images.
"""

import argparse
import pathlib as pl
import sys
from typing import Callable

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent.parent.absolute()))

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.common import init_logging
from tests.end_to_end_tests.container_images_test.tools import (
    get_image_builder_by_name,
    build_test_version_of_container_image,
)
from agent_build_refactored.container_images.image_builders import (
    ImageType,
    ALL_CONTAINERISED_AGENT_BUILDERS,
    SUPPORTED_ARCHITECTURES,
)

init_logging()


def add_command_line_args(add_func: Callable):
    add_func(
        "--image-builder-name",
        required=True,
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    add_func("--image-type", required=True, choices=[t.value for t in ImageType])

    add_func(
        "--architecture",
        required=True,
        choices=[a.value for a in SUPPORTED_ARCHITECTURES],
    )

    add_func(
        "--image-oci-tarball",
        required=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    add_command_line_args(
        add_func=parser.add_argument,
    )

    parser.add_argument(
        "--result-image-name",
        required=True,
    )

    args = parser.parse_args()

    image_builder_cls = get_image_builder_by_name(name=args.image_builder_name)

    build_test_version_of_container_image(
        image_type=ImageType(args.image_type),
        image_builder_cls=image_builder_cls,
        architecture=CpuArch(args.architecture),
        result_image_name=args.result_image_name,
        ready_image_oci_tarball=args.image_oci_tarball,
    )
