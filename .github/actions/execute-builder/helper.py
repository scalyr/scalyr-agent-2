# Copyright 2014-2022 Scalyr Inc.
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
This is a helper script for the GitHub Actions CI/CD that allows to run cacheable steps of a tools.builder.Builder class.
"""

import argparse
import json
import pathlib as pl
import sys

_SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.parent
# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

from agent_build.agent_builders import ALL_BUILDERS, get_builders_all_cacheable_steps
from tests.package_tests import all_package_tests

if __name__ == '__main__':


    parser = argparse.ArgumentParser()

    parser.add_argument(
        "name",
        choices=ALL_BUILDERS.keys(),
        help="Name of the builder."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    get_builder_step_ids_parser = subparsers.add_parser(
        "get-cacheable-steps-ids",
        help="Print in standard output a JSON encoded list of ids of all cacheable steps that are used by builder."
    )

    execute_builder_parser = subparsers.add_parser(
        "execute-cacheable-steps",
        help="Runs all cacheable steps that are used by builder."
    )

    execute_builder_parser.add_argument(
        "--build-root-dir",
        dest="build_root_dir",
        required=True
    )

    args = parser.parse_args()

    builder_cls = ALL_BUILDERS[args.name]

    if args.command == "get-cacheable-steps-ids":
        builder_cacheable_steps = get_builders_all_cacheable_steps(builder_cls)
        print(json.dumps(
            [s.id for s in builder_cacheable_steps]
        ))
        exit(0)

    if args.command == "execute-cacheable-steps":
        for step in builder_cls.CACHEABLE_STEPS:
            step.run(
                build_root=pl.Path(args.build_root_dir).absolute()
            )