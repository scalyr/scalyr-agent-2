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
import logging
import pathlib as pl
import argparse
import sys
import pathlib as pl

from typing import Dict, Type

logging.basicConfig(level=logging.INFO)

if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.absolute()))

from agent_build_refactored.docker_image_builders import (
    ALL_IMAGE_BUILDERS,
)
from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_PACKAGE_BUILDERS,
)

from agent_build_refactored.tools.builder import Builder


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    package_parser = subparsers.add_parser("package")

    package_parser.add_argument(
        "package_builder_name",
        choices=ALL_PACKAGE_BUILDERS.keys(),
    )
    package_parser.add_argument(
        "--output-dir",
        default=str(SOURCE_ROOT / "build")
    )

    args = parser.parse_args()

    if args.command == "package":
        package_builder_cls = ALL_PACKAGE_BUILDERS[args.package_builder_name]

        builder = package_builder_cls()
        builder.build(
            output_dir=pl.Path(args.output_dir),
        )
        exit(0)
