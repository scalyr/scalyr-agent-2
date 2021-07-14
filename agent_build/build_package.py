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


import sys
import pathlib as pl
import argparse

PARENT_DIR = pl.Path(__file__).absolute().parent
SOURCE_ROOT = PARENT_DIR.parent

print(SOURCE_ROOT)
sys.path.append(str(SOURCE_ROOT))

from agent_build import package_builder
from agent_build import common

# This build script support additional functionality which should be useful for CI/CD to cache the build dependencies
# and decrease the build time. Those two options does not affect the build process and used to be able to cache the
# dependencies which are used during the build.

parser = argparse.ArgumentParser()


package_types_to_builders = {
    "deb": package_builder.DebPackageBuilder,
    "rpm": package_builder.RpmPackageBuilder,
    "tar": package_builder.TarballPackageBuilder,
    "msi": package_builder.WindowsMsiPackageBuilder
}

parser.add_argument(
    "package_type",
    type=str,
    choices=list(package_types_to_builders.keys()),
    help="Type of the package to build.")

subparsers = parser.add_subparsers(dest="command")

prepare_environment_parser = subparsers.add_parser("prepare-environment")

prepare_environment_parser.add_argument(
    "--content-checksum-path", type=str, dest="content_checksum_path",
    help="Calculate the checksum of the content of all files that are used in the build and dump it into the file"
         " located in the specified path. This is useful to calculate the cache key for CI/CD"
)

prepare_environment_parser.add_argument(
    "--cache-dependencies-path", type=str, dest="cache_dependencies_path",
    help="The directory where the build dependencies has to be cached. This should be mostly "
         "used by CI/CD to reduce the build time."
)

build_parser = subparsers.add_parser("build")

build_parser.add_argument(
    "--output-dir", required=True, type=str, dest="output_dir",
    help="The directory where the result package has to be stored."
)
build_parser.add_argument(
    "--locally", action="store_true",
    help="Some of the packages by default are build inside the docker to provide consistent build environment."
         "Inside the docker this script is executed once more, but with the '--locally' option, "
         "so it's aware that it should build the package directly in the docker."
)

build_parser.add_argument(
    "--no-versioned-file-name",
    action="store_true",
    dest="no_versioned_file_name",
    default=False,
    help="If true, will not embed the version number in the artifact's file name.  This only "
         "applies to the `tarball` and container builders artifacts.",
)


args, other_argv = parser.parse_known_args()

package_builder_cls = package_types_to_builders[args.package_type]


if args.command == "prepare-environment":
    if args.content_checksum_path:
        # this is a special case when we dump the checksum of all files which are used in the build. This checksum
        # them can be used as a key for CI/CD cache.
        builder = package_builder_cls()
        builder.dump_dependencies_content_checksum(
            content_checksum_path=args.content_checksum_path
        )
        exit(0)

    if args.cache_dependencies_path:
        builder = package_builder_cls()
        print("0000")
        print(args.cache_dependencies_path)
        builder.prepare_dependencies(
            cache_dir=args.cache_dependencies_path,
        )
        exit(0)
elif args.command == "build":
    output_path = pl.Path(args.output_dir).absolute()
    output_path.mkdir(exist_ok=True, parents=True)
    build_info = common.PackageBuildInfo(
        build_summary=common.get_build_info(),
        no_versioned_file_name=args.no_versioned_file_name
    )
    package_builder_cls(
        locally=args.locally
    ).build(
        build_info=build_info,
        output_path=output_path
    )
