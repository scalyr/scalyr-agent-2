# Copyright 2014-2023 Scalyr Inc.
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


import pathlib as pl
import subprocess
from typing import Type

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.docker.common import delete_container
from agent_build_refactored.utils.docker.buildx.build import buildx_build, DockerImageBuildOutput
from agent_build_refactored.container_images.image_builders import (
    ALL_CONTAINERISED_AGENT_BUILDERS,
    ContainerisedAgentBuilder,
    ImageType,
)

_PARENT_DIR = pl.Path(__file__).parent


def build_test_version_of_container_image(
    image_type: ImageType,
    image_builder_cls: Type[ContainerisedAgentBuilder],
    architecture: CpuArch,
    result_image_name: str,
    ready_image_oci_tarball: pl.Path = None,
):
    """Get production image create it's testable version."""

    image_builder = image_builder_cls()

    registry_container_name = "agent_image_e2e_test_registry"

    delete_container(
        container_name=registry_container_name
    )

    # Create temporary local registry to push production image there.
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p=5000:5000",
            f"--name={registry_container_name}",
            "registry:2",
        ],
        check=True
    )
    try:
        all_image_tags = image_builder.generate_final_registry_tags(
            image_type=image_type,
            registry="localhost:5000",
            user="user",
            tags=["prod"],
        )

        # Publish image to the local registry
        image_builder.publish(
            image_type=image_type,
            tags=all_image_tags,
            existing_oci_layout_dir=ready_image_oci_tarball
        )

        prod_image_tag = all_image_tags[0]

        # Build agent image requirements, because it also includes requirements for testing.
        requirement_libs_dir = image_builder.build_requirement_libs(
            architecture=architecture,
        )

        # Build testable image.
        buildx_build(
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            context_path=_PARENT_DIR,
            architecture=architecture,
            build_contexts={
                "prod_image": f"docker-image://{prod_image_tag}",
                "requirement_libs": str(requirement_libs_dir),
            },
            output=DockerImageBuildOutput(
                name=result_image_name,
            )
        )
    finally:
        delete_container(
            container_name=registry_container_name
        )

    return result_image_name


def get_image_builder_by_name(name: str):
    return ALL_CONTAINERISED_AGENT_BUILDERS[name]