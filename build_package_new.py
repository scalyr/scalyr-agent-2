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

# This is a new package build script which uses new package  build logic.
# usage:
#       build_package_new.py <name of the package> --output-dir <output directory>

import logging
import pathlib as pl
import argparse
import sys

if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_build.tools import common
from agent_build.package_build_steps import DOCKER_IMAGE_BUILDERS, run_docker_image_builder

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"

common.init_logging()


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    # Add subparsers for all packages except docker builders.
    subparsers = parser.add_subparsers(dest="package_name", required=True)

    all_package_builders = DOCKER_IMAGE_BUILDERS.copy()

    for builder_name, builder in all_package_builders.items():
        package_parser = subparsers.add_parser(name=builder_name)

        # Define argument for all packages
        package_parser.add_argument(
            "--locally",
            action="store_true",
            help="Perform the build on the current system which runs the script. Without that, some packages may be built "
            "by default inside the docker.",
        )

        package_parser.add_argument(
            "--no-versioned-file-name",
            action="store_true",
            dest="no_versioned_file_name",
            default=False,
            help="If true, will not embed the version number in the artifact's file name.  This only "
            "applies to the `tarball` and container builders artifacts.",
        )

        package_parser.add_argument(
            "-v",
            "--variant",
            dest="variant",
            default=None,
            help="An optional string that is included in the package name to identify a variant "
            "of the main release created by a different packager.  "
            "Most users do not need to use this option.",
        )

        package_parser.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug mode with additional logging.",
        )

        # If that's a docker image builder, then add additional commands.
        if builder_name in DOCKER_IMAGE_BUILDERS:
            package_parser.add_argument(
                "--registry",
                help="Registry (or repository) name where to push the result image.",
            )

            package_parser.add_argument(
                "--user", help="User name prefix for the image name."
            )

            package_parser.add_argument(
                "--tag",
                action="append",
                help="The tag that will be applied to every registry that is specified. Can be used multiple times.",
            )

            package_parser.add_argument(
                "--push", action="store_true", help="Push the result docker image."
            )

            package_parser.add_argument(
                "--testing",
                dest="testing",
                action="store_true",
                default=False,
                help="Build test versions of the image that contain additional features, for example enabled coverage. "
                     "Can be used in smoketests. Only works with docker/k8s.",
            )

        else:

            # Add output dir argument. It is required only for non-docker image builds.
            package_parser.add_argument(
                "--output-dir",
                required=True,
                type=str,
                dest="output_dir",
                help="The directory where the result package has to be stored.",
            )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        for logger in loggers:
            logger.setLevel(logging.DEBUG)

    # Find the builder class.
    builder_name = args.package_name

    # If that's a docker image builder handle their arguments too.
    if builder_name in DOCKER_IMAGE_BUILDERS:
        run_docker_image_builder(
            image_builder_name=builder_name,
            registry=args.registry,
            user=args.user,
            tags=args.tag or [],
            push=args.push,
            testing=args.testing
        )
        exit(0)
