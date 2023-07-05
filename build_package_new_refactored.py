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

from typing import Dict, Type

if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_build_refactored.tools import UniqueDict, init_logging
from agent_build_refactored.tools.runner import Runner
from agent_build_refactored.docker_image_builders import (
    ALL_IMAGE_BUILDERS,
)
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_PACKAGE_BUILDERS,
)
from agent_build_refactored.tools.builder import BUILDER_CLASSES, Builder
from agent_build_refactored.scripts.builder_helper import builder_main


logging.basicConfig(level=logging.INFO)


ALL_BUILDERS: Dict[str, Type[Builder]] = {
    **ALL_IMAGE_BUILDERS,
    **ALL_PACKAGE_BUILDERS
}

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"

#
# BUILDERS: Dict[str, Runner] = UniqueDict(
#     **ALL_IMAGE_BUILDERS, **ALL_MANAGED_PACKAGE_BUILDERS
# )

if __name__ == "__main__":

    init_logging()

    # First, we use base parser just to parse the builder name.
    # When we determine the name, we create another parser which will be used by the builder itself.
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("builder_name", choices=ALL_BUILDERS.keys())

    # base_parser.add_argument(
    #     "--fqdn",
    #     dest="fqdn",
    #     action="store_true",
    #     help="If this flag specified then just print fully qualified name for the builder. Mainly needed for CI/CD.",
    # )

    base_args, other_argv = base_parser.parse_known_args()

    builder_cls = ALL_BUILDERS[base_args.builder_name]

    builder_main(
        builder_fqdn=builder_cls.FQDN,
        argv=other_argv,
    )

    a=10

    #
    # builder_cls = BUILDER_CLASSES[base_args.builder_name]
    #
    # if base_args.fqdn:
    #     print(builder_cls.get_fully_qualified_name())
    #     exit(0)
    #
    # # Create parser for builder commands and parse them.
    # parser = argparse.ArgumentParser()
    #
    # builder_cls.add_command_line_arguments(parser=parser)
    #
    # args = parser.parse_args(args=other_args)
    #
    # builder_cls.handle_command_line_arguments(args=args)
