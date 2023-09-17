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

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent.parent.absolute()))

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.common import init_logging
from tests.end_to_end_tests.container_images_test.tools import (
    get_image_builder_by_name,
    build_test_version_of_container_image,
    add_command_line_args,
)
from agent_build_refactored.container_images.image_builders import (
    ImageType,
)

init_logging()

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

    image_builder = image_builder_cls(base_image=args.base_image)

    if args.image_oci_tarball:
        image_oci_tarball = pl.Path(args.image_oci_tarball)
    else:
        image_oci_tarball = None

    build_test_version_of_container_image(
        image_type=ImageType(args.image_type),
        image_builder=image_builder,
        architecture=CpuArch(args.architecture),
        result_image_name=args.result_image_name,
        ready_image_oci_tarball=image_oci_tarball,
        install_additional_test_libs=not args.do_not_install_additional_test_libs,
    )
