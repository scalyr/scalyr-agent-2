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

import pathlib as pl
import argparse
import sys
import logging

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(__SOURCE_ROOT__))

from agent_build import package_builders

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s"
    )

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "package_name",
        type=str,
        choices=package_builders.ALL_PACKAGE_BUILDERS.keys(),
        help="Type of the package to build.",
    )

    parser.add_argument(
        "--locally",
        action="store_true",
        help="Perform the build on the current system which runs the script. Without that, some packages may be built "
        "by default inside the docker.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        type=str,
        dest="output_dir",
        help="The directory where the result package has to be stored.",
    )

    parser.add_argument(
        "--no-versioned-file-name",
        action="store_true",
        dest="no_versioned_file_name",
        default=False,
        help="If true, will not embed the version number in the artifact's file name.  This only "
        "applies to the `tarball` and container builders artifacts.",
    )

    parser.add_argument(
        "-v",
        "--variant",
        dest="variant",
        default=None,
        help="An optional string that is included in the package name to identify a variant "
        "of the main release created by a different packager.  "
        "Most users do not need to use this option.",
    )

    args = parser.parse_args()

    # Find the builder class.
    package_builder = package_builders.ALL_PACKAGE_BUILDERS[args.package_name]

    logging.info(f"Build package '{args.package_name}'...")

    package_builder.build(output_path=pl.Path(args.output_dir), locally=args.locally)
