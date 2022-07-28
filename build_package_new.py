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

from typing import Dict

if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_build.tools import common
from agent_build.tools.environment_deployments.deployments import CacheableBuilder
from agent_build.package_builders import DOCKER_IMAGE_PACKAGE_BUILDERS

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"

common.init_logging()


BUILDERS: Dict[str, CacheableBuilder]  = {
        **DOCKER_IMAGE_PACKAGE_BUILDERS,
}

if __name__ == "__main__":
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("builder_name", choices=BUILDERS.keys())

    base_parser.add_argument(
        "--fqdn",
        dest="fqdn",
        action="store_true"
    )

    base_args, other_args = base_parser.parse_known_args()

    builder_cls = BUILDERS[base_args.builder_name]

    if base_args.fqdn:
        print(builder_cls.get_fully_qualified_name())
        exit(0)

    parser = argparse.ArgumentParser()

    builder_cls.add_command_line_arguments(parser=parser)

    args = parser.parse_args(args=other_args)

    builder_cls.handle_command_line_arguments(args=args)