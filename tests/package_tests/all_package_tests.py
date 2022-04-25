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


from agent_build.tools import constants
from tests.package_tests.internals import docker_test, k8s_test
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker
from agent_build.tools import common
from agent_build.tools.build_step import SimpleBuildStep, ScriptBuildStep
from agent_build.package_build_steps import IMAGE_BUILDS, BuildStep, FinalStep

_PARENT_DIR = pl.Path(__file__).parent
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.absolute()

# The global collection of all test. It is used by CI aimed scripts in order to be able to perform those test just
# by knowing the name of needed test.
ALL_PACKAGE_TESTS: Dict[str, "Test"] = {}
#
# # Maps package test of some package to the builder of this package. Also needed for the GitHub Actions CI to
# # create a job matrix for a particular package tests.
# PACKAGE_BUILDER_TESTS: Dict[
#     package_builders.PackageBuilder, List["Test"]
# ] = collections.defaultdict(list)


# class Test:
#     """
#     Particular package test. If combines information about the package type, architecture,
#     deployment and the system where test has to run.
#     """
#
#     def __init__(
#         self,
#         base_name: str,
#         package_builder_name: str,
#         additional_deployment_steps: List[Type[deployments.DeploymentStep]] = None,
#         deployment_architecture: constants.Architecture = None,
#     ):
#         """
#         :param base_name: Base name of the test.
#         :param package_builder: Builder instance to build the image.
#         :param additional_deployment_steps: Additional deployment steps that may be needed to perform the test.
#             They are additionally performed after the deployment steps of the package builder.
#         :param deployment_architecture: Architecture of the machine where the test's deployment has to be perform.
#             by default it is an architecture of the package builder.
#         """
#         self._base_name = base_name
#         self.package_builder = package_builder
#         self.architecture = deployment_architecture or package_builder.architecture
#
#         additional_deployment_steps = additional_deployment_steps or []
#
#         # since there may be needed to build the package itself first, we have to also deploy the steps
#         # from the package builder's deployment, to provide needed environment for the builder,
#         # so we add the steps from the builder's deployment first.
#         additional_deployment_steps = [
#             *[type(step) for step in package_builder.deployment.steps],
#             *additional_deployment_steps,
#         ]
#
#         self.deployment = deployments.Deployment(
#             name=self.unique_name,
#             step_classes=additional_deployment_steps,
#             architecture=deployment_architecture or package_builder.architecture,
#             base_docker_image=package_builder.base_docker_image,
#         )
#
#         if self.unique_name in ALL_PACKAGE_TESTS:
#             raise ValueError(
#                 f"The package test with name: {self.unique_name} already exists."
#             )
#
#         # Add the current test to the global tests collection so it can be invoked from command line.
#         ALL_PACKAGE_TESTS[self.unique_name] = self
#         # Also add it to the package builders tests collection.
#         PACKAGE_BUILDER_TESTS[self.package_builder].append(self)
#
#     @property
#     def unique_name(self) -> str:
#         """
#         The unique name of the package test. It contains information about all specifics that the test has.
#         """
#         return f"{self.package_builder.name}_{self._base_name}".replace("-", "_")


class DockerImagePackageTest(FinalStep):
    BUILD_NAME: str
    """
    Test for the agent docker images.
    """

    def __init__(
        self,
        scalyr_api_key: str,
        name_suffix: str = None,
    ):
        """
        :param target_image_architectures: List of architectures in which to perform the image tests.
        :param base_name: Base name of the test.
        :param package_builder: Builder instance to build the image.
        :param additional_deployment_steps: Additional deployment steps that may be needed to perform the test.
            They are additionally performed after the deployment steps of the package builder.
        :param deployment_architecture: Architecture of the machine where the test's deployment has to be perform.
            by default it is an architecture of the package builder.
        """

        self._build_name = type(self).BUILD_NAME
        build_cls = IMAGE_BUILDS[self._build_name]

        self._registry_host = "localhost:5050"
        self._tags = ["test"]

        self._scalyr_api_key = scalyr_api_key
        self._name_suffix = name_suffix

        self._build = build_cls(
            registry=self._registry_host,
            tags=self._tags,
            push=True
        )

        super().__init__(
            used_steps=self._build.all_used_cacheable_steps
        )

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
        registry_container = build_in_docker.LocalRegistryContainer(
            name="agent_images_registry", registry_port=5050
        )

        def _test_pushed_image():

            # Test that all tags has been pushed to the registry.
            for tag in ["latest", "test", "debug"]:
                logging.info(
                    f"Test that the tag '{tag}' is pushed to the registry '{self._registry_host}'"
                )

                for image_name in self._build.RESULT_IMAGE_NAMES:
                    full_image_name = f"{self._registry_host}/{image_name}:{tag}"

                    # Remove the local image first, if exists.
                    logging.info("    Remove existing image.")
                    subprocess.check_call(
                        ["docker", "image", "rm", "-f", full_image_name]
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
                        subprocess.check_call(["docker", "pull", full_image_name])
                    except subprocess.CalledProcessError:
                        logging.exception(
                            "    Can not pull the result image from local registry."
                        )

                    # Check if the tested image contains needed distribution.
                    if "debian" in self._build_name:
                        expected_os_name = "debian"
                    elif "alpine" in self._build_name:
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
                                str(full_image_name),
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
                        ["docker", "image", "rm", "-f", full_image_name]
                    )

            # Use any of variants of the image name to test it.
            local_registry_image_name = (
                f"{self._registry_host}/{self._build.RESULT_IMAGE_NAMES[0]}"
            )

            # Start the tests for each architecture.
            # TODO: Make tests run in parallel.
            for arch in [
                constants.Architecture.X86_64,
                constants.Architecture.ARM64,
                constants.Architecture.ARMV7
            ]:
                logging.info(
                    f"Start testing image '{local_registry_image_name}' with architecture "
                    f"'{arch.as_docker_platform}'"
                )

                if "k8s" in self._build_name:
                    k8s_test.run(
                        image_name=local_registry_image_name,
                        architecture=arch,
                        scalyr_api_key=self._scalyr_api_key,
                        name_suffix=self._name_suffix,
                    )
                else:
                    docker_test.run(
                        image_name=local_registry_image_name,
                        architecture=arch,
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
                        self._build_name,
                        "--registry",
                        self._registry_host,
                        "--tag",
                        "latest",
                        "--tag",
                        "test",
                        "--tag",
                        "debug",
                        "--push",
                    ],
                    cwd=str(__SOURCE_ROOT__),
                )
                _test_pushed_image()
        finally:
            # Cleanup.
            # Removing registry container.
            subprocess.check_call(["docker", "logout", self._registry_host])

            subprocess.check_call(["docker", "image", "prune", "-f"])


DOCKER_IMAGE_TESTS = {}
for build_name in IMAGE_BUILDS:
    class ImageTest(DockerImagePackageTest):
        BUILD_NAME = build_name

    test_name = f"{build_name}-test"
    DOCKER_IMAGE_TESTS[test_name] = ImageTest