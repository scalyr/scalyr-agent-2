#!/usr/bin/env python3

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
This step script gets result platform-specific base image tarballs from its required/child steps
and combines them into one  multi-arch base image.

It expects next env-variables:
    BASE_IMAGE_NAME_PREFIX: Prefix for the name of the result image.

    it also expects set of env variables with naming format: '_BASE_PLATFORM_STEP_<platform_name>', and these
    variables store paths to outputs of the required/child steps, where platform-specific images are stored.
"""

import os
import pathlib as pl

from agent_build_refactored.tools.steps_libs.container import LocalRegistryContainer
from agent_build_refactored.tools.steps_libs.subprocess_with_log import (
    check_output_with_log,
    check_call_with_log,
)
from agent_build_refactored.tools.steps_libs.build_logging import init_logging


def main():
    registry_final_image_name = (
        f"localhost:{reg.real_registry_port}/{BASE_IMAGE_NAME_PREFIX}"
    )

    docker_manifest_command_args = [
        "docker",
        "buildx",
        "imagetools",
        "create",
        "-t",
        registry_final_image_name,
    ]

    # Search for env. variables that store output paths of corresponding base platform-specific image builder steps.
    # Such variables name has to begin with special prefix.
    for n, base_step_output_path in os.environ.copy().items():
        if not n.startswith("_BASE_PLATFORM_STEP_"):
            continue

        base_step_output_path = pl.Path(base_step_output_path)

        # Find tarball with platform-specific image.
        found = list(base_step_output_path.glob(f"{BASE_IMAGE_NAME_PREFIX}*.tar"))

        assert (
            len(found) == 1
        ), f"Number of result image tarball for each platform-specific builder step has to be 1, but got '{found}'"

        tarball_path = found[0]

        # Image name has to be the same as tarball name
        image_name = tarball_path.stem
        registry_image_name = f"localhost:{reg.real_registry_port}/{image_name}"

        load_output_bin = check_output_with_log(
            ["docker", "load", "-i", str(tarball_path)],
            description=f"Load image from tarball '{tarball_path}'",
        )

        # Get id from the loaded image to tag it with appropriate name.
        load_output = load_output_bin.decode().strip()
        image_id = load_output.split(":")[-1]

        check_call_with_log(
            ["docker", "tag", image_id, registry_image_name],
            description=f"Tag loaded platform-specific image with id '{image_id} to '{registry_image_name}'",
        )

        check_call_with_log(
            ["docker", "push", registry_image_name],
            description=f"Push platform-specific image '{registry_image_name}'",
        )

        docker_manifest_command_args.extend([registry_image_name])

    check_call_with_log(
        [*docker_manifest_command_args],
        description=f"Create and push manifest of the new multi-arch base image '{registry_final_image_name}'.",
    )


if __name__ == "__main__":
    init_logging()

    BASE_IMAGE_NAME_PREFIX = os.environ["BASE_IMAGE_NAME_PREFIX"]
    STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])

    CONTAINER_NAME = "agent_base_image_build"

    registry_data_root = STEP_OUTPUT_PATH / "registry"

    # Start registry container where result image will be stored.
    with LocalRegistryContainer(
        name="agent_base_image_build",
        registry_port=0,
        registry_data_path=registry_data_root,
    ) as reg:
        main()
