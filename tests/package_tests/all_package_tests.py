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


import collections
import pathlib as pl
import subprocess
import sys
import logging
from typing import Dict, List, Type

import agent_build.tools.common
from tests.package_tests.internals import docker_test, k8s_test
from agent_build.tools import common
from agent_build.tools.builder import Builder
from agent_build.agent_builders import ImageBuilder, IMAGE_BUILDS, AGENT_DOCKER_IMAGE_SUPPORTED_ARCHITECTURES
from agent_build.tools.common import LocalRegistryContainer

_PARENT_DIR = pl.Path(__file__).parent
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.absolute()

# The global collection of all test. It is used by CI aimed scripts in order to be able to perform those test just
# by knowing the name of needed test.
ALL_PACKAGE_TESTS: Dict[str, "Test"] = {}


class DockerImagePackageTest(Builder):
    IMAGE_BUILD_CLS: Type[ImageBuilder]
    """
    Test for the agent docker images.
    """

    def __init__(
        self,
        scalyr_api_key: str,
        name_suffix: str = None,
    ):
        """
        :param scalyr_api_key: API key to use during package tests.
        :param name_suffix: A special suffix to a name of a created container or cluster.
        """

        self._build_cls = type(self).IMAGE_BUILD_CLS

        self._registry_host = "localhost:5050"
        self._tags = ["test"]

        self._scalyr_api_key = scalyr_api_key
        self._name_suffix = name_suffix

        self._build = self._build_cls(
            registry=self._registry_host,
            tags=self._tags,
            push=True
        )

        super().__init__()

    def _run(
        self
    ):
        """
        Run test for the agent docker image.
        First of all it builds an image, then pushes it to the local registry and does full test.

        :param scalyr_api_key:  Scalyr API key.
        :param name_suffix: Additional suffix to the agent instance name.
        """

        # Run container with docker registry.
        logging.info("Run new local docker registry in container.")
        registry_container = LocalRegistryContainer(
            name="agent_images_registry", registry_port=5050
        )

        def _test_pushed_image():
            tags_to_test = ["latest", "test", "debug"]
            tag_options = []
            all_image_names_to_test = []
            for tag in tags_to_test:
                for image_name in self._build.RESULT_IMAGE_NAMES:
                    full_image_name = f"{self._registry_host}/{image_name}:{tag}"
                    tag_options.extend([
                        "-t",
                        full_image_name
                    ])
                    all_image_names_to_test.append(full_image_name)

            for full_image_name in all_image_names_to_test:

                full_testing_image_name = f"{full_image_name}"
                subprocess.check_call([
                    "docker",
                    "buildx",
                    "build",
                    "-t",
                    full_testing_image_name,
                    "-f",
                    str(agent_build.tools.common.SOURCE_ROOT / "agent_build" / "docker" / "Dockerfile.final-testing"),
                    "--build-arg",
                    f"BASE_IMAGE={full_testing_image_name}",
                    "--push",
                    str(agent_build.tools.common.SOURCE_ROOT)
                ])

                # Remove the local image first, if exists.
                logging.info("    Remove existing image.")
                subprocess.check_call(
                    ["docker", "image", "rm", "-f", full_testing_image_name]
                )

                logging.info("    Log in to the local registry.")
                # Login to the local registry.
                subprocess.check_call(
                    [
                        "docker",
                        "login",
                        "--password",
                        "nopass",
                        "--username",
                        "nouser",
                        self._registry_host,
                    ]
                )

                # Pull the image
                logging.info("    Pull the image.")
                try:
                    subprocess.check_call(["docker", "pull", full_testing_image_name])
                except subprocess.CalledProcessError:
                    logging.exception(
                        "    Can not pull the result image from local registry."
                    )

                # Check if the tested image contains needed distribution.
                if "debian" in self._build.NAME:
                    expected_os_name = "debian"
                elif "alpine" in self._build.NAME:
                    expected_os_name = "alpine"
                else:
                    raise AssertionError(
                        f"Test does not contain os name (debian or alpine)"
                    )

                # Get the content of the 'os-release' file from the image and verify the distribution name.
                os_release_content = (
                    common.check_output_with_log(
                        [
                            "docker",
                            "run",
                            "-i",
                            "--rm",
                            str(full_testing_image_name),
                            "/bin/cat",
                            "/etc/os-release",
                        ]
                    )
                    .decode()
                    .lower()
                )

                assert (
                    expected_os_name in os_release_content
                ), f"Expected {expected_os_name}, got {os_release_content}"

                # Remove the image once more.
                logging.info("    Remove existing image.")
                subprocess.check_call(
                    ["docker", "image", "rm", "-f", full_testing_image_name]
                )

            # Use any of variants of the image name to test it.
            local_registry_image_name = (
                f"{self._registry_host}/{self._build.RESULT_IMAGE_NAMES[0]}:latest"
            )

            # Start the tests for each architecture.
            # TODO: Make tests run in parallel.
            for arch in AGENT_DOCKER_IMAGE_SUPPORTED_ARCHITECTURES:
                logging.info(
                    f"Start testing image '{local_registry_image_name}' with architecture "
                    f"'{arch.as_docker_platform}'"
                )

                if "k8s" in self._build.NAME:
                    k8s_test.run(
                        image_name=local_registry_image_name,
                        architecture=arch.as_docker_platform,
                        scalyr_api_key=self._scalyr_api_key,
                        name_suffix=self._name_suffix,
                    )
                else:
                    docker_test.run(
                        image_name=local_registry_image_name,
                        docker_platform=arch.as_docker_platform,
                        scalyr_api_key=self._scalyr_api_key,
                        name_suffix=self._name_suffix,
                    )

        try:
            with registry_container:
                # Build image and push it to the local registry.
                # Instead of calling the build function run the build_package script,
                # so it can also be tested.
                logging.info("Build docker image")
                subprocess.check_call(
                    [
                        sys.executable,
                        "build_package_new.py",
                        self._build.NAME,
                        "--registry",
                        self._registry_host,
                        "--tag",
                        "latest",
                        "--tag",
                        "test",
                        "--tag",
                        "debug",
                        "--push",
                        "--build-root-dir",
                        str(self._build_root),
                        "--testing",

                    ],
                    cwd=str(__SOURCE_ROOT__),
                )
                _test_pushed_image()
        finally:
            # Cleanup.
            # Removing registry container.
            subprocess.check_call(["docker", "logout", self._registry_host])

            subprocess.check_call(["docker", "image", "prune", "-f"])


DOCKER_IMAGE_TESTS: [str, Type[Builder]] = {}
for build_name in IMAGE_BUILDS:
    build_cls = IMAGE_BUILDS[build_name]

    test_name = f"{build_name}-test"

    class ImageTest(DockerImagePackageTest):
        NAME = test_name
        IMAGE_BUILD_CLS = build_cls
        CACHEABLE_STEPS = [*build_cls.CACHEABLE_STEPS]


    DOCKER_IMAGE_TESTS[test_name] = ImageTest