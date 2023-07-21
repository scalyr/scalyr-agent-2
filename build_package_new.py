# Copyright 2014-2021 Scalyr Inc.
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
This is a new package build script which uses new package build logic.
usage:
      build_package_new.py <name of the package>

to see all available packages to build use:
    build_package_new.py --help


Commands line arguments for the particular package builder are defined within the builder itself,
to see those options use build_package_new.py <name of the package> --help.
"""
import argparse
import sys
import pathlib as pl

if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.absolute()))

from agent_build_refactored.utils.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.utils.common import init_logging
from agent_build_refactored.container_images.image_builders import (
    ALL_CONTAINERISED_AGENT_BUILDERS,
    ImageType,
)

init_logging()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image")

    image_parser.add_argument(
        "builder_name",
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    image_parser_action_subparsers = image_parser.add_subparsers(dest="action", required=True)

    def _add_image_type_arg(_parser):
        _parser.add_argument(
            "--image-type",
            required=True,
            choices=[t.value for t in ImageType],
        )

    load_image_parser = image_parser_action_subparsers.add_parser("load")
    _add_image_type_arg(load_image_parser)
    load_image_parser.add_argument(
        "--image-name",
        required=True,
    )

    image_build_parser = image_parser_action_subparsers.add_parser("build-tarball")
    _add_image_type_arg(image_build_parser)
    image_build_parser.add_argument(
        "--output-dir",
        required=True,
    )

    cache_requirements_image_parser = image_parser_action_subparsers.add_parser("cache-requirements")
    cache_requirements_image_parser.add_argument(
        "--architecture",
        required=True,
    )

    image_publish_parser = image_parser_action_subparsers.add_parser("publish")
    _add_image_type_arg(image_publish_parser)
    image_publish_parser.add_argument(
        "--registry",
        required=False,
        default="docker.io",
    )

    image_publish_parser.add_argument(
        "--user",
        required=True,
    )
    image_publish_parser.add_argument(
        "--tags",
        required=True,
    )
    image_publish_parser.add_argument(
        "--from-oci-layout-dir",
        required=False,
    )
    image_publish_parser.add_argument(
        "--registry-username",
        required=False,
    )
    image_publish_parser.add_argument(
        "--registry-password",
        required=False,
    )

    args = parser.parse_args()

    if args.command == "image":
        image_builder_cls = ALL_CONTAINERISED_AGENT_BUILDERS[args.builder_name]

        builder = image_builder_cls()
        if args.action == "load":
            builder.build_and_load_docker_image(
                image_type=ImageType(args.image_type),
                result_image_name=args.image_name,
            )
        if args.action == "build-tarball":
            if args.output_dir:
                output_dir = pl.Path(args.output_dir)
            else:
                output_dir = None

            builder.build_oci_tarball(
                image_type=ImageType(args.image_type),
                output_dir=output_dir
            )
            exit(0)
        elif args.action == "cache-requirements":
            builder.build_requirement_libs(
                architecture=CpuArch(args.architecture),
            )

        elif args.action == "publish":
            tags = args.tags.split(",")

            if args.from_oci_layout_dir:
                existing_oci_layout_dir = pl.Path(args.from_oci_layout_dir)
            else:
                existing_oci_layout_dir = None

            final_tags = builder.generate_final_registry_tags(
                image_type=ImageType(args.image_type),
                registry=args.registry,
                user=args.user,
                tags=tags
            )
            builder.publish(
                image_type=ImageType(args.image_type),
                tags=final_tags,
                existing_oci_layout_dir=existing_oci_layout_dir,
                registry_username=args.registry_username,
                registry_password=args.registry_password,
            )
            exit(0)
