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
This script generates job matrices for GitHub Actions. This is needed because we do a full - "extended" run on GHA
when we push on master or create a pull request, in other cases (e.g. just custom development branch)
we just run limited set of tests.
"""

import argparse
import json
import sys
import pathlib as pl
from typing import List, Type

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent))


from agent_build.tools.runner import Runner, RunnerStep
from agent_build.docker_image_builders import (
    ContainerImageBuilder,
    DEBIAN_IMAGE_BUILDERS,
    ALPINE_IMAGE_BUILDERS,
    IMAGES_PYTHON_VERSION,
    ALL_DOCKER_IMAGE_BUILDERS,
)

from tests.end_to_end_tests.container_image_tests.k8s_test.parameters import (
    DEFAULT_K8S_TEST_PARAMS,
    ALL_K8S_TEST_PARAMS,
)

from tests.end_to_end_tests.container_image_tests.docker_test.parameters import (
    DEFAULT_DOCKER_TEST_PARAMS,
    ALL_DOCKER_TEST_PARAMS,
)

DEFAULT_IMAGE_BUILDERS = DEBIAN_IMAGE_BUILDERS[:]
ADDITIONAL_IMAGE_BUILDERS = [*ALPINE_IMAGE_BUILDERS]


def get_image_build_matrix(extended: bool):
    """
    Gets GHA-recognizable job matrix for agent image build job.
    :param extended: Build all images if True.
    """

    builders = (
        list(ALL_DOCKER_IMAGE_BUILDERS.values()) if extended else DEFAULT_IMAGE_BUILDERS
    )

    matrix = {"include": []}

    for builder_cls in builders:
        matrix["include"].append(
            {
                "builder-name": builder_cls.get_name(),
                "distro-name": builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.name,
                "python-version": f"{IMAGES_PYTHON_VERSION}",
                "os": "ubuntu-20.04",
            }
        )

    print(json.dumps(matrix))


def _get_pre_built_step_runners(
    runner_classes: List[Type[Runner]],
) -> List[Type[Runner]]:
    """
    This function collect all required RunnerStep instances from all provided Runner classes that have to be pre-built
    on a separate job in GHA, and wraps each of them into a "dummy" Runner class that runs only that particular step.
    Later, such dummy runners then can be executed in a separate GHA job.
    """

    # Filter only for pre-built steps

    all_pre_built_steps = {}
    for runner_cls in runner_classes:
        for step in runner_cls.get_all_cacheable_steps():
            if not step.github_actions_settings.pre_build_in_separate_job:
                continue
            all_pre_built_steps[step.id] = step

    all_pre_built_step_runners = []
    for step in all_pre_built_steps.values():
        # Create "dummy" Runner for each runner step that has to be pre-built, this dummy runner will be executed
        # by its fqdn to run the step.
        class StepWrapperRunner(Runner):
            REQUIRED_STEPS = [step]

        # Since this runner class is created dynamically we have to generate a constant fqdn for it.
        StepWrapperRunner.assign_fully_qualified_name(
            class_name=StepWrapperRunner.__name__,
            module_name=__name__,
            class_name_suffix=step.id,
        )
        all_pre_built_step_runners.append(StepWrapperRunner)

    return all_pre_built_step_runners


# Create "dummy" step runners for pre-built steps job matrix.
DEFAULT_IMAGES_PRE_BUILT_STEP_RUNNERS = _get_pre_built_step_runners(
    DEFAULT_IMAGE_BUILDERS
)
ADDITIONAL_IMAGES_PRE_BUILT_STEP_RUNNERS = _get_pre_built_step_runners(
    ADDITIONAL_IMAGE_BUILDERS
)
EXTENDED_IMAGES_PRE_BUILT_STEP_RUNNERS = [
    *DEFAULT_IMAGES_PRE_BUILT_STEP_RUNNERS,
    *ADDITIONAL_IMAGES_PRE_BUILT_STEP_RUNNERS,
]


def get_image_pre_built_steps_matrix(extended: bool):
    """
    Create GHA job matrix for thejob which pre-builds runner steps which are marked to be done so.
    """

    all_image_req_step_runners = (
        EXTENDED_IMAGES_PRE_BUILT_STEP_RUNNERS
        if extended
        else DEFAULT_IMAGES_PRE_BUILT_STEP_RUNNERS
    )

    matrix = {"include": []}

    for builder_cls in all_image_req_step_runners:
        matrix["include"].append(
            {
                "name": f"Pre-build: {builder_cls.REQUIRED_STEPS[0].name}",
                "step-runner-fqdn": builder_cls.get_fully_qualified_name(),
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))


def get_k8s_image_test_matrix(extended: bool):
    """
    Get GHA job matrix for k8s image test job.
    """
    params = ALL_K8S_TEST_PARAMS if extended else DEFAULT_K8S_TEST_PARAMS
    matrix = {"include": []}

    for p in params:
        image_builder_name = p["image_builder_name"]
        image_builder_cls = ALL_DOCKER_IMAGE_BUILDERS[image_builder_name]
        kubernetes_version = p["kubernetes_version"]
        minikube_driver = p["minikube_driver"]
        container_runtime = p["container_runtime"]

        matrix["include"].append(
            {
                "pytest-params": f"{image_builder_name}-{kubernetes_version}-{minikube_driver}-{container_runtime}",
                "builder-name": image_builder_name,
                # "distro-name": image_builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.name,
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))


def get_docker_images_test_matrix(extended: bool):
    params = ALL_DOCKER_TEST_PARAMS if extended else DEFAULT_DOCKER_TEST_PARAMS
    matrix = {"include": []}

    for p in params:
        image_builder_name = p["image_builder_name"]

        matrix["include"].append(
            {
                "pytest-params": f"{image_builder_name}",
                "builder-name": image_builder_name,
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("matrix_name")

    parser.add_argument("--extended", required=False, action="store_true")

    args = parser.parse_args()

    if args.matrix_name == "pre_built_steps_matrix":
        get_image_pre_built_steps_matrix(extended=args.extended)
        exit(0)

    if args.matrix_name == "image_build_matrix":
        get_image_build_matrix(extended=args.extended)
        exit(0)

    if args.matrix_name == "k8s_image_test_matrix":
        get_k8s_image_test_matrix(extended=args.extended)
        exit(0)

    if args.matrix_name == "docker_image_test_matrix":
        get_docker_images_test_matrix(extended=args.extended)
        exit(0)


if __name__ == "__main__":
    main()
