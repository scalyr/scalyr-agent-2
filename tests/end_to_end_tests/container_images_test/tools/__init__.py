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
from typing import Callable

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.docker.common import delete_container
from agent_build_refactored.utils.docker.buildx.build import (
    buildx_build,
    DockerImageBuildOutput,
)
from agent_build_refactored.container_images import ALL_CONTAINERISED_AGENT_BUILDERS
from agent_build_refactored.container_images.image_builders import (
    ContainerisedAgentBuilder,
    ImageType,
)

_PARENT_DIR = pl.Path(__file__).parent


def build_test_version_of_container_image(
    image_type: ImageType,
    image_builder: ContainerisedAgentBuilder,
    architecture: CpuArch,
    result_image_name: str,
    ready_image_oci_tarball: pl.Path = None,
    install_additional_test_libs: bool = True,
):
    """
    Get production image create it's testable version.
    For now, it adds just a coverage library as additional requirements, so our image
    tests can enable it in order to obtain coverage information of the docker/k8s related code.
    """

    registry_container_name = "agent_image_e2e_test_registry"

    delete_container(container_name=registry_container_name)

    # Create temporary local registry to push production image there.
    cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "-p=5000:5000",
        f"--name={registry_container_name}",
        "registry:2",
    ]

    print(f"Creating local registry container: {cmd}")

    completed_process = subprocess.run(
        cmd,
        check=True,
        capture_output=True
    )

    print(completed_process.stdout.decode())
    print(completed_process.stderr.decode())

    try:
        all_image_tags = image_builder.generate_final_registry_tags(
            image_type=image_type,
            registry="localhost:5000",
            name_prefix="user",
            tags=["prod"],
        )

        # Publish image to the local registry
        print(f"Publishing image to the local registry: {all_image_tags}")
        image_builder.publish(
            image_type=image_type,
            tags=all_image_tags,
            existing_oci_layout_tarball=ready_image_oci_tarball,
            no_verify_tls=True,
        )

        prod_image_tag = all_image_tags[0]
        if install_additional_test_libs:

            # Build agent image requirements, because it also includes requirements (like coverage) for testing.
            requirement_libs_dir = image_builder.build_requirement_libs(
                architecture=architecture,
            )

            # Build testable image.
            buildx_build(
                dockerfile_path=_PARENT_DIR / "Dockerfile",
                context_path=_PARENT_DIR,
                architectures=[architecture],
                build_contexts={
                    "prod_image": f"docker-image://{prod_image_tag}",
                    "requirement_libs": str(requirement_libs_dir),
                },
                output=DockerImageBuildOutput(
                    name=result_image_name,
                ),
            )
        else:
            subprocess.run(
                [
                    "docker",
                    "pull",
                    prod_image_tag,
                ],
                check=True,
            )

            subprocess.run(
                [
                    "docker",
                    "tag",
                    prod_image_tag,
                    result_image_name,
                ],
                check=True,
            )
    finally:
        delete_container(container_name=registry_container_name)

    return result_image_name


def get_image_builder_by_name(name: str):
    return ALL_CONTAINERISED_AGENT_BUILDERS[name]


def add_command_line_args(add_func: Callable):
    add_func(
        "--image-builder-name",
        required=True,
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    add_func("--base-image", required=True, help="Name of the image to build")

    add_func("--image-type", required=True, choices=[t.value for t in ImageType])

    add_func(
        "--architecture",
        required=True,
        choices=[a.value for a in CpuArch],
    )

    add_func(
        "--image-oci-tarball",
        required=False,
        help="Instead of building an image. Use existing oce from the given OCI image.",
    )

    add_func(
        "--do-not-install-additional-test-libs",
        required=False,
        action="store_true",
        help="Do not install additional libraries to a tested images.",
    )
