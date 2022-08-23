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
import sys
import pathlib as pl
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

# We expect some info from the GitHub actions context to determine if the run is 'master-only' or not.
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")
GITHUB_BASE_REF = os.environ.get("GITHUB_BASE_REF", "")
GITHUB_REF_TYPE = os.environ.get("GITHUB_REF_TYPE", "")
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "")

to_publish = False

# We do a full, 'master' workflow run on:
# pull request against the 'master' branch.
if GITHUB_EVENT_NAME == "pull_request" and GITHUB_BASE_REF == "master":
    master_run = True
# push to the 'master' branch
elif (
    GITHUB_EVENT_NAME == "push"
    and GITHUB_REF_TYPE == "branch"
    and GITHUB_REF_NAME == "master"
):
    master_run = True
    to_publish = True

# push to a "production" tag.
elif GITHUB_EVENT_NAME == "push" and GITHUB_REF_TYPE == "tag":
    version_file_path = SOURCE_ROOT / "VERSION"
    current_version = version_file_path.read_text().strip()
    if GITHUB_REF_NAME == f"v{current_version}":
        master_run = True
        to_publish = True

else:
    master_run = False


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


def _apply_job_defaults(job: Dict[str, str]):
    """
    Set default values for some essential job matrix fields (if not specified).
    """
    if "os" not in job:
        job["os"] = "ubuntu-20.04"
    if "python-version" not in job:
        job["python-version"] = IMAGES_PYTHON_VERSION


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

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--images-build-matrix-json-file",
        dest="images_build_matrix_json_file",
        required=True,
        help="Path to a JSON file with images build job matrix."
    )
    parser.add_argument(
        "--k8s-images-test-matrix-json-file",
        dest="k8s_images_test_matrix_json_file",
        required=True,
        help="Path to a JSON file with Kubernetes images test job matrix."
    )
    parser.add_argument(
        "--docker-images-test-matrix-json-file",
        dest="docker_images_test_matrix_json_file",
        required=True,
        help="Path to a JSON file with docker images test job matrix."
    )

    args = parser.parse_args()
    images_build_matrix_json_file_path = pl.Path(args.images_build_matrix_json_file)

    images_build_matrix = json.loads(
        images_build_matrix_json_file_path.read_text()
    )

    # List of all runners that are used by this workflow run.
    used_runners = []

    # Generate a final agent image build job matrix and filter out job for non-master run, if needed.
    result_images_build_matrix = {"include": []}
    for job in images_build_matrix:
        is_master_run_only = job.get("master_run_only", True)

        # If this is non-master run, skip jobs which are not supposed to be in it.
        if is_master_run_only and not master_run:
            continue

        _apply_job_defaults(job)

        builder_name = job["name"]
        builder = ALL_IMAGE_BUILDERS[builder_name]
        job["builder-fqdn"] = builder.get_fully_qualified_name()
        result_images_build_matrix["include"].append(job)
        used_runners.append(builder)

    k8s_images_test_matrix_json_file_path = pl.Path(args.k8s_images_test_matrix_json_file)

    # Generate a final agent k8s image test job matrix and filter out job for non-master run, if needed.
    k8s_images_test_matrix = json.loads(
        k8s_images_test_matrix_json_file_path.read_text()
    )
    result_k8s_images_test_matrix = {"include": []}
    for job in k8s_images_test_matrix:
        is_master_run_only = job.get("master_run_only", True)
        # If this is non-master run, skip jobs which are not supposed to be in it.
        if is_master_run_only and not master_run:
            continue
        _apply_job_defaults(job)
        result_k8s_images_test_matrix["include"].append(job)

    # Generate a final agent docker image test job matrix and filter out job for non-master run, if needed.
    docker_images_test_matrix_json_file_path = pl.Path(args.docker_images_test_matrix_json_file)
    docker_images_test_matrix = json.loads(
        docker_images_test_matrix_json_file_path.read_text()
    )
    result_docker_images_test_matrix = {"include": []}
    for job in docker_images_test_matrix:
        is_master_run_only = job.get("master_run_only", True)
        # If this is non-master run, skip jobs which are not supposed to be in it.
        if is_master_run_only and not master_run:
            continue
        _apply_job_defaults(job)
        result_docker_images_test_matrix["include"].append(job)

    # Get pre-built steps that are used by this workflow and create matrix for a pre-built steps.
    pre_built_steps = _get_runners_all_pre_built_steps(
        runners=used_runners
    )
    pre_build_steps_matrix = {"include": []}

    for pre_built_step in pre_built_steps.values():
        pre_built_step_runner = _pre_built_step_runners[pre_built_step.id]
        pre_build_steps_matrix["include"].append(
            {
                "name": f"Pre-build: {pre_built_step_runner.REQUIRED_STEPS[0].name}",
                "step-runner-fqdn": pre_built_step_runner.get_fully_qualified_name(),
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    all_matrices = {
        "pre_build_steps_matrix": pre_build_steps_matrix,
        "agent_image_build_matrix": result_images_build_matrix,
        "k8s_test_matrix_json": result_k8s_images_test_matrix,
        "docker_test_matrix_json": result_docker_images_test_matrix,
        "to_publish": to_publish
    }

    print(json.dumps(all_matrices))


if __name__ == "__main__":
    main()
