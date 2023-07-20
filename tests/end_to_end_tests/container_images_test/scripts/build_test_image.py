import argparse
import pathlib as pl
import sys

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent.parent.absolute()))

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.common import init_logging
from tests.end_to_end_tests.container_images_test.conftest import add_command_line_args
from tests.end_to_end_tests.container_images_test.tools import (
    get_image_builder_by_name,
    build_test_version_of_container_image,
)
from agent_build_refactored.container_images.image_builders import ImageType

init_logging()


if __name__ == '__main__':
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
