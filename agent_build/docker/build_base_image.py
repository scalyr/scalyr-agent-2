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

import os
import pathlib as pl
import re
import subprocess

from agent_build.tools.steps_libs.container import LocalRegistryContainer

# from agent_build.tools.steps_libs.subprocess_with_log import


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
        if not n.startswith("_BASE_PLATFORM_IMAGE_STEP_"):
            continue

        base_step_output_path = pl.Path(base_step_output_path)

        found = list(base_step_output_path.glob(f"{BASE_IMAGE_NAME_PREFIX}*.tar"))

        assert (
            len(found) == 1
        ), "Number of result image tarball for each platform-specific builder step has to be 1."

        tarball_path = found[0]

        platform_suffix = re.search(
            rf"{re.escape(BASE_IMAGE_NAME_PREFIX)}-([^-]+-[^-]+-[^-]*)",
            tarball_path.stem,
        ).group(1)

        image_name = f"{BASE_IMAGE_NAME_PREFIX}:{platform_suffix}"
        registry_image_name = f"localhost:{reg.real_registry_port}/{image_name}"

        load_output_bin = subprocess.check_output(
            ["docker", "load", "-i", str(tarball_path)]
        )
        load_output = load_output_bin.decode().strip()
        image_id = load_output.split(":")[-1]

        subprocess.check_call(["docker", "tag", image_id, registry_image_name])

        # Push it to local registry.
        subprocess.check_call(["docker", "push", registry_image_name])

        docker_manifest_command_args.extend([registry_image_name])

    subprocess.check_call([*docker_manifest_command_args])


if __name__ == "__main__":
    BASE_IMAGE_NAME_PREFIX = os.environ["BASE_IMAGE_NAME_PREFIX"]
    STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])

    CONTAINER_NAME = "agent_base_image_build"

    registry_data_root = STEP_OUTPUT_PATH / "registry"
    with LocalRegistryContainer(
        name="agent_base_image_build",
        registry_port=0,
        registry_data_path=registry_data_root,
    ) as reg:
        main()
