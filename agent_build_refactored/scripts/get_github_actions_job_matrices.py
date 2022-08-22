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
This script generates job matrices for GitHub Actions. This is needed because we do a "full" run on GHA
when we push on master or create a pull request, in other cases (e.g. just custom development branch)
we just run limited set of tests to reduce number of jobs for active development phase.
"""
import argparse
import json
import os
import sys
import pathlib as pl
from typing import List, Type

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent))

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner
from agent_build_refactored.docker_image_builders import IMAGES_PYTHON_VERSION

from agent_build_refactored.docker_image_builders import (
    DEBIAN_IMAGE_BUILDERS,
    ALL_IMAGE_BUILDERS,
)

# We expect some info from the GitHub actions context to determine if the run is limited or not.
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")
GITHUB_BASE_REF = os.environ.get("GITHUB_BASE_REF", "")
GITHUB_REF_TYPE = os.environ.get("GITHUB_REF_TYPE", "")
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "")

limited_run = True

# We do a full workflow run on:
# pull request against the 'master' branch.
if GITHUB_EVENT_NAME == "pull_request" and GITHUB_BASE_REF == "master":
    limited_run = False
# push to the 'master' branch
elif (
    GITHUB_EVENT_NAME == "push"
    and GITHUB_REF_TYPE == "branch"
    and GITHUB_REF_NAME == "master"
):
    limited_run = False

# push to a "production" tag.
elif GITHUB_EVENT_NAME == "push" and GITHUB_REF_TYPE == "tag":
    version_file_path = SOURCE_ROOT / "VERSION"
    current_version = version_file_path.read_text().strip()
    if GITHUB_REF_NAME == f"v{current_version}":
        limited_run = False

# Set collection of builders that will be used during the CI/Cd workflow run.

# if limited_run:
#     used_image_builders = DEBIAN_IMAGE_BUILDERS[:]
# else:
#     used_image_builders = list(ALL_IMAGE_BUILDERS.values())

# agent_images_build_matrix = {"include": []}
# for builder_cls in used_image_builders:
#     agent_images_build_matrix["include"].append(
#         {
#             "builder-name": builder_cls.get_name(),
#             "builder-fqdn": builder_cls.get_fully_qualified_name(),
#             "python-version": f"{IMAGES_PYTHON_VERSION}",
#             "os": "ubuntu-20.04",
#         }
#     )


def _get_all_pre_build_step_jobx_matrix(used_builders: List[Type[Runner]]):
    # Search for all steps that are used by all used runners.
    _all_used_runner_steps = {}
    for runner_cls in used_builders:
        for step in runner_cls.get_all_cacheable_steps():
            if not step.github_actions_settings.pre_build_in_separate_job:
                continue
            _all_used_runner_steps[step.id] = step

    pre_build_steps_matrix = {"include": []}
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
        pre_build_steps_matrix["include"].append(
            {
                "name": f"Pre-build: {StepWrapperRunner.REQUIRED_STEPS[0].name}",
                "step-runner-fqdn": StepWrapperRunner.get_fully_qualified_name(),
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    return pre_build_steps_matrix


def main():

    run_type_name = "limited" if limited_run else "full"
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

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--images-build-matrix-json-file",
        dest="images_build_matrix_json_file",
        required=True,
        help="Path to a JSON file with images build job matrix."
    )

    args = parser.parse_args()
    images_build_matrix_json_file_path = pl.Path(args.images_build_matrix_json_file)
    images_build_matrix = json.loads(
        images_build_matrix_json_file_path.read_text()
    )

    result_images_build_matrix = {"include": []}
    used_builders = []

    for job in images_build_matrix:
        is_basic = job.get("basic", False)
        if not is_basic and limited_run:
            continue
        result_images_build_matrix["include"].append(job)
        builder_name = job["name"]
        used_builders.append(ALL_IMAGE_BUILDERS[builder_name])

    all_matrices = {
        "agent_image_build_matrix": result_images_build_matrix,
        "pre_build_steps_matrix": _get_all_pre_build_step_jobx_matrix(used_builders=used_builders)
    }

    print(json.dumps(all_matrices))


if __name__ == "__main__":
    main()
