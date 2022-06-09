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

# PLEASE NOTE. To achieve valid caching of the build step, keep that script as standalone as possible.
#   If there are any dependencies, imports or files which are used by this script, then also specify them
#   in the `tracked_file_globs` argument during creation of the step class instance.

"""
This script is used in the build step that builds base image for Agent's Docker image.
"""

from typing import List
import os
import subprocess
import pathlib as pl
import json

SOURCE_ROOT = pl.Path(os.environ["SOURCE_ROOT"])
STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])
REGISTRY_OUTPUT_PATH = STEP_OUTPUT_PATH / "output_registry"

_CONTAINER_NAME = "agent_base_image_registry_step"


def kill_registry_container():
    subprocess.check_call([
        "docker",
        "rm",
        "-f",
        _CONTAINER_NAME
    ])


def main(
    platforms_to_build: List[str],
    result_image_name: str,
    python_base_image_name: str,
):

    # Clear previously created container, ix exists
    kill_registry_container()

    # Spin up local registry in container.
    subprocess.check_call([
        "docker",
        "run",
        "-d",
        "--rm",
        "-p",
        "5005:5000",
        "-v",
        f"{REGISTRY_OUTPUT_PATH}:/var/lib/registry",
        "--name",
        _CONTAINER_NAME,
        "registry:2"
    ])

    # # Also write a special file to the output where we specify a platform of the result image,
    # # it will be needed to the final image builder step.
    # ARCHITECTURE_INFO_FILE_OUTPUT_PATH.write_text(platforms_to_build)

    platform_options = []

    for p in platforms_to_build:
        platform_options.append("--platform"),
        platform_options.append(p)

    def build(testing: bool):

        testing_args = []
        result_image_final_name = f"localhost:5005/{result_image_name}"
        if testing:
            testing_args = [
                "--build-arg",
                f"TESTING=1"
            ]
            result_image_final_name = f"{result_image_final_name}-testing"

        subprocess.check_call([
            "docker",
            "buildx",
            "build",
            "-t",
            result_image_final_name,
            "-f",
            f"{SOURCE_ROOT}/agent_build/docker/Dockerfile.base",
            "--push",
            "--build-arg",
            f"PYTHON_BASE_IMAGE_NAME={python_base_image_name}",
            *testing_args,
            *platform_options,
            str(SOURCE_ROOT)
        ])

    build(False)
    build(True)


if __name__ == '__main__':
    main(
        platforms_to_build=json.loads(os.environ["PLATFORMS_TO_BUILD"]),
        result_image_name=os.environ["RESULT_IMAGE_NAME"],
        python_base_image_name=os.environ["PYTHON_BASE_IMAGE_NAME"],
    )