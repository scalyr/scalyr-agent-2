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
This script gets job matrices that are specified in the workflow and filters out jobs that are not supposed to be
in the "master" run - run which is only from 'master' branch or from 'master'-targeted PR.

It also generates matrix for job that have to run a special pre-built steps.
"""
import argparse
import json
import os
import subprocess
import sys
import pathlib as pl
import time
import re
from distutils.version import StrictVersion
from typing import List, Type, Dict

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent))

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerStep
from agent_build_refactored.docker_image_builders import IMAGES_PYTHON_VERSION

from agent_build_refactored.docker_image_builders import (
    ALL_IMAGE_BUILDERS,
)

from agent_build_refactored.managed_packages.managed_packages_builders import ALL_MANAGED_PACKAGE_BUILDERS

# We expect some info from the GitHub actions context to determine if the run is 'master-only' or not.
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")
GITHUB_BASE_REF = os.environ.get("GITHUB_BASE_REF", "")
GITHUB_REF_TYPE = os.environ.get("GITHUB_REF_TYPE", "")
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_SHA = os.environ.get("GITHUB_SHA", "")


def is_branch_has_pull_requests():

    data = subprocess.check_output([
        "curl",
        "-H",
        f"Authorization: Bearer {GITHUB_TOKEN}",
        f"https://api.github.com/repos/ArthurKamalov/scalyr-agent-2/pulls?head=ArthurKamalov:{GITHUB_REF_NAME}&base=master",
    ]).decode().strip()

    pull_requests = json.loads(data)
    return len(pull_requests) > 0


def determine_last_prod_version():

    subprocess.check_call([
        "git", "fetch", "--unshallow", "--tags"
    ])
    output = subprocess.check_output([
        "git", "--no-pager", "tag", "-l"
    ]).decode()

    production_tags = []
    for tag in output.splitlines():
        m = re.search(r"^v(\d+\.\d+\.\d+)$", tag)
        if m is None:
            continue

        production_tags.append(m.group(1))

    last_version = sorted(production_tags, key=StrictVersion)[-1]
    return f"v{last_version}"


PROD_VERSION = determine_last_prod_version()
DEV_VERSION = f"{PROD_VERSION}.{int(time.time())}.{GITHUB_SHA}"

# We do a full, 'master' workflow run on:
# pull request against the 'master' branch.
if GITHUB_EVENT_NAME == "pull_request" and GITHUB_BASE_REF == "master":
    master_run = True
    to_publish = False
    is_production = False
    version = DEV_VERSION
# push to the 'master' branch
elif (
    GITHUB_EVENT_NAME == "push"
    and GITHUB_REF_TYPE == "branch"
    and GITHUB_REF_NAME == "master"
):
    master_run = True
    to_publish = True
    is_production = False
    version = DEV_VERSION

# push to a "production" tag.
elif GITHUB_EVENT_NAME == "push" and GITHUB_REF_TYPE == "tag":
    to_publish = True
    master_run = True
    m = re.match(r"^v\d+\.\d+\.\d+$", GITHUB_REF_NAME)

    if m:
        is_production = True
        version = GITHUB_REF_NAME
    else:
        is_production = False
        version = f"{PROD_VERSION}.{int(time.time())}.{GITHUB_REF_NAME}"

else:
    master_run = is_branch_has_pull_requests()
    to_publish = False
    is_production = False
    version = DEV_VERSION


ALL_USED_RUNNERS = {
    **ALL_IMAGE_BUILDERS
}


def _get_runners_all_pre_built_steps(runners: List[Type[Runner]]) -> Dict[str, RunnerStep]:
    """
    Get collection of all RunnerSteps that are used by the Runners from the given list.
    :return: Dict with all used RunnerSteps. Step ID - key, step - value.
    """
    _all_runner_steps = {}
    for runner_cls in runners:
        for step in runner_cls.get_all_cacheable_steps():
            if not step.github_actions_settings.pre_build_in_separate_job:
                continue
            _all_runner_steps[step.id] = step
    return _all_runner_steps


# Search for all steps that are used by given runners.
_all_used_runner_steps = _get_runners_all_pre_built_steps(
    runners=list(ALL_USED_RUNNERS.values())
)

# Create runner for each found pre-built step.
_pre_built_step_runners = {}
for step in _all_used_runner_steps.values():
    # Create "dummy" Runner for each runner step that has to be pre-built, this dummy runner will be executed
    # by its fqdn to run the step.
    class StepWrapperRunner(Runner):
        REQUIRED_STEPS = [step]

    # Since this runner class is created dynamically we have to generate a constant fqdn for it.
    StepWrapperRunner.assign_fully_qualified_name(
        class_name="pre-built-",
        module_name=__name__,
        class_name_suffix=step.id,
    )
    _pre_built_step_runners[step.id] = StepWrapperRunner


def _get_managed_packages_build_matrix(
        input_build_matrix: List
):

    # List of all runners that are used by this workflow run.
    used_runners = []

    # Generate a final agent image build job matrix and filter out job for non-limited run, if needed.
    result_matrix = {"include": []}
    for job in input_build_matrix:
        is_master_run_only = job.get("master_run_only", True)

        # If this is non-master run, skip jobs which are not supposed to be in it.
        if is_master_run_only and not master_run:
            continue

        # Set default valued for some essential matrix values, if not specified.
        if "os" not in job:
            job["os"] = "ubuntu-20.04"
        if "python-version" not in job:
            job["python-version"] = IMAGES_PYTHON_VERSION

        builder_name = job["name"]
        builder = ALL_MANAGED_PACKAGE_BUILDERS[builder_name]
        job["builder-fqdn"] = builder.get_fully_qualified_name()
        result_matrix["include"].append(job)
        used_runners.append(builder)

    return result_matrix


def _get_managed_packages_test_matrix(
        input_test_matrix: List
):

    # List of all runners that are used by this workflow run.
    used_runners = []

    # Generate a final agent image build job matrix and filter out job for non-limited run, if needed.
    result_matrix = {"include": []}
    for job in input_test_matrix:
        is_master_run_only = job.get("master_run_only", True)

        # If this is non-master run, skip jobs which are not supposed to be in it.
        if is_master_run_only and not master_run:
            continue

        # Set default valued for some essential matrix values, if not specified.
        if "os" not in job:
            job["os"] = "ubuntu-20.04"
        if "python-version" not in job:
            job["python-version"] = IMAGES_PYTHON_VERSION

        builder_name = job["name"]
        builder = ALL_MANAGED_PACKAGE_BUILDERS[builder_name]
        job["builder-fqdn"] = builder.get_fully_qualified_name()
        result_matrix["include"].append(job)
        used_runners.append(builder)

    return result_matrix


def main():
    run_type_name = "master" if master_run else "non-master"
    print(
        f"Doing {run_type_name} workflow run.",
        file=sys.stderr
    )
    print(
        f"event_name: {GITHUB_EVENT_NAME}\n"
        f"base_ref: {GITHUB_BASE_REF}\n"
        f"ref_type: {GITHUB_REF_TYPE}\n"
        f"ref_name: {GITHUB_REF_NAME}",
        file=sys.stderr,
    )

    result = {
        "agent_image_build_matrix": result_images_build_matrix,
        "agent_managed_packages_build_matrix": result_managed_packages_build_matrix,
        "agent_managed_packages_test_matrix": result_managed_packages_test_matrix,
        "pre_build_steps_matrix": pre_build_steps_matrix,
        "is_master_run": master_run,
        "to_publish": to_publish,
        "is_production": is_production,
        "version": version
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
