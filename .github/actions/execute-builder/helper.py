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
This is a helper script for the GitHub Actions CI/CD that allows to run cacheable steps of StepRunners
from the agent_build package.
"""

import argparse
import json
import pathlib as pl
import sys
from typing import Type, Dict

_SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.parent
# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

from agent_build.tools.builder import Builder
from agent_build.agent_builders import IMAGE_BUILDS
from tests.package_tests.all_package_tests import DOCKER_IMAGE_TESTS

if __name__ == '__main__':

    all_runners: Dict[str, Type[Builder]] = {
        **IMAGE_BUILDS,
        **DOCKER_IMAGE_TESTS
    }

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "name",
        choices=all_runners.keys(),
        help="Name of the step runner."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    get_runner_step_ids_parser = subparsers.add_parser(
        "get-cacheable-steps-ids",
        help="Print in standard output a JSON encoded list of ids of all cacheable steps that are used by runner."
    )

    execute_runner_parser = subparsers.add_parser(
        "execute",
        help="Runs all cacheable steps that are used by runner."
    )

    execute_runner_parser.add_argument(
        "--build-root-dir",
        dest="build_root_dir",
        required=True
    )

    args = parser.parse_args()

    runner = all_runners[args.name]

    if args.command == "get-cacheable-steps-ids":
        print(json.dumps(
            runner.all_used_cacheable_steps_ids()
        ))
        exit(0)

    if args.command == "execute":
        for step in runner.all_used_cacheable_steps():
            step.run(
                build_root=pl.Path(args.build_root_dir)
            )