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
This script accepts command line arguments to operate with deployments (see agent_build/tools/environment_deployments/deployments.py).
Mainly, the script created for the GitHub Action local action - '.github/actions/preform-deployment' to provide ability
to use deployments and cache their results by using Github Actions caching mechanism.

Usage:
    List all available deployments (not used anywhere, but may be useful for debug and manual usage of deployments):

        run_deployment.py list

    Perform some deployment (used by Github Action CI):

        run_deployment.py deployment <deployment_name> deploy

    Get names of all caches of all steps of the deployment (used by Github Action CI).

        run_deployment.py deployment <deployment_name> get-deployment-all-cache-names

        Each step has its own unique cache name, so our local GutHub action can cache step's results to its own,
        separate cache in the Github Actions. That means that the step that is used by many deployments will be cached
        only once and will be reused by those deployments.

        Also a utility command for the Github Action CI to perform the trick with caching, that has been described
            above. The local GitHub action uses those names as cache keys for GitHub Action cache.

"""

import sys
import pathlib as pl
import argparse
import json

_SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

from agent_build.tools.environment_deployments import deployments
from agent_build import package_builders
from agent_build.tools import common


if __name__ == "__main__":
    common.init_logging()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    get_list_parser = subparsers.add_parser("list")
    deployment_subparser = subparsers.add_parser("deployment")
    deployment_subparser.add_argument(
        "deployment_name", choices=deployments.ALL_DEPLOYMENTS.keys()
    )

    deployment_subparsers = deployment_subparser.add_subparsers(
        dest="deployment_command", required=True
    )
    deploy_parser = deployment_subparsers.add_parser("deploy")

    get_all_deployments_parser = deployment_subparsers.add_parser(
        "get-deployment-all-cache-names"
    )

    args = parser.parse_args()

    if args.command == "deployment":

        deployment = deployments.ALL_DEPLOYMENTS[args.deployment_name]
        if args.deployment_command == "deploy":
            # Perform the deployment with specified name.
            deployment.deploy()
            exit(0)

        if args.deployment_command == "get-deployment-all-cache-names":
            # A special command which is needed to perform the Github action located in
            # '.github/actions/perform-deployment'. The command provides names of the caches of the deployment's steps,
            # so the Github action knows what keys to use to cache the results of those steps.

            # Get cache names of from all steps and print them as JSON list. This format is required by the mentioned
            # Github action.
            step_checksums = []
            for step in deployment.steps:
                step_checksums.append(step.cache_key)

            print(json.dumps(list(reversed(step_checksums))))

            exit(0)

    if args.command == "list":
        for deployment_name in sorted(deployments.ALL_DEPLOYMENTS.keys()):
            print(deployment_name)
        exit(0)
