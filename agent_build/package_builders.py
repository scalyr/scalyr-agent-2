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

"""
This module defines all possible packages of the Scalyr Agent and how they can be built.
"""
import argparse
import dataclasses
import enum
import json
import pathlib as pl
import shlex
import tarfile
import abc
import shutil
import time
import sys
import stat
import os
import logging
from typing import List

from agent_build.tools import constants
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker
from agent_build.tools import common
from agent_build.tools.constants import Architecture, PackageType
from agent_build.tools.environment_deployments.deployments import ShellScriptDeploymentStep, DeploymentStep, CacheableBuilder, BuilderInput
from agent_build.prepare_agent_filesystem import build_linux_lfs_agent_files, get_install_info, create_change_logs
from agent_build.tools.constants import SOURCE_ROOT
from agent_build.tools.common import check_output_with_log


__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

_AGENT_BUILD_PATH = __SOURCE_ROOT__ / "agent_build"


class ContainerImageBuilder(CacheableBuilder):
    """
    The base builder for all docker and kubernetes based images . It builds an executable script in the current working
     directory that will build the container image for the various Docker and Kubernetes targets.
     This script embeds all assets it needs in it so it can be a standalone artifact. The script is based on
     `docker/scripts/container_builder_base.sh`. See that script for information on it can be used."
    """
    # Path to the configuration which should be used in this build.
    CONFIG_PATH = None

    # Names of the result image that goes to dockerhub.
    RESULT_IMAGE_NAMES: List[str]

    BASE_IMAGE_BUILDER_STEP: deployments.BuildDockerBaseImageStep

    def __init__(
            self,
            registry: str = None,
            tags: List[str] = None,
            user: str = None,
            push: bool = False,
            platforms: List = None,
            only_filesystem_tarball: str = None,
            use_test_version: bool = False,
    ):
        """
        :param registry: Registry (or repository) name where to push the result image.
        :param tags: The tag that will be applied to every registry that is specified. Can be used multiple times.
        :param user: User name prefix for the image name.
        :param push: Push the result docker image.
        :param platforms: Comma delimited list of platforms to build (and optionally push) the image for.
        :param only_filesystem_tarball: Build only the tarball with the filesystem of the agent. This argument has to
            accept path to the directory where the tarball is meant to be built. Used by the Dockerfile itself and does
            not required to be run manually.
        :param use_test_version: Build a special version of image with additional measuring tools (such as coverage).
            Used only for testing."
        """
        self._name = type(self).NAME
        self.config_path = type(self).CONFIG_PATH

        self.dockerfile_path = __SOURCE_ROOT__ / "agent_build/docker/Dockerfile"

        base_image_deployment_step = type(self).BASE_IMAGE_BUILDER_STEP

        self.use_test_version = use_test_version
        self.registry = registry
        self.tags = tags or []
        self.user = user
        self.push = push

        self.only_filesystem_tarball = only_filesystem_tarball and pl.Path(only_filesystem_tarball)
        if self.only_filesystem_tarball:
            self.only_filesystem_tarball = pl.Path(only_filesystem_tarball)

        platforms = platforms
        if platforms is None:
            self.base_image_deployment_step = base_image_deployment_step
            self.platforms = self.base_image_deployment_step.platforms
        else:
            self.platforms = platforms
            self.base_image_deployment_step = type(base_image_deployment_step)(
                name="agent-docker-base-image-custom",
                python_image_suffix=base_image_deployment_step.python_image_suffix,
                platforms=platforms
            )

        super(ContainerImageBuilder, self).__init__(
            deployment_step=self.base_image_deployment_step
        )

        self._package_root_path = self.output_path / "package_root"

    @property
    def name(self) -> str:
        # Container builders are special since we have an instance per Dockerfile since different
        # Dockerfile represents a different builder
        return self._name

    def _build_package_files(self):

        build_linux_lfs_agent_files(
            copy_agent_source=True,
            output_path=self._package_root_path,
            config_path=type(self).CONFIG_PATH,
        )

        # Need to create some docker specific directories.
        pl.Path(self._package_root_path / "var/log/scalyr-agent-2/containers").mkdir()

    def build_filesystem_tarball(self):
        self._build_package_files()

        container_tarball_path = self.output_path / "scalyr-agent.tar.gz"

        # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
        # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
        # mainly Posix.
        with tarfile.open(container_tarball_path, "w:gz") as container_tar:

            for root, dirs, files in os.walk(self._package_root_path):
                to_copy = []
                for name in dirs:
                    to_copy.append(os.path.join(root, name))
                for name in files:
                    to_copy.append(os.path.join(root, name))

                for x in to_copy:
                    file_entry = container_tar.gettarinfo(
                        x, arcname=str(pl.Path(x).relative_to(self._package_root_path))
                    )
                    file_entry.uname = "root"
                    file_entry.gname = "root"
                    file_entry.uid = 0
                    file_entry.gid = 0

                    if file_entry.isreg():
                        with open(x, "rb") as fp:
                            container_tar.addfile(file_entry, fp)
                    else:
                        container_tar.addfile(file_entry)

        self.only_filesystem_tarball.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(container_tarball_path, self.only_filesystem_tarball)

    def _build(self, locally: bool = False):
        """
        This function builds Agent docker image by using the specified dockerfile (defaults to "Dockerfile").
        It passes to dockerfile its own package type through docker build arguments, so the same package builder
        will be executed inside the docker build to prepare inner container filesystem.

        The result image is built upon the base image that has to be built by the deployment of this builder.
            Since it's not a trivial task to "transfer" a multi-platform image from one place to another, the image is
            pushed to a local registry in the container, and the root of that registry is transferred instead.

        Registry's root in /var/lib/registry is exposed to the host by using docker's mount feature and saved in the
            deployment's output directory. This builder then spins up another local registry container and mounts root
            of the saved registry. Now builder can refer to this local registry in order to get the base image.

        """

        if self.only_filesystem_tarball:
            self.build_filesystem_tarball()
            return

        registry_data_path = self.base_image_deployment_step.output_directory / "output_registry"

        # Create docker buildx builder instance. # Without it the result image won't be pushed correctly
        # to the local registry.
        buildx_builder_name = "agent_image_buildx_builder"

        # print docker and buildx version
        docker_version_output = (
            common.check_output_with_log(["docker", "version"]).decode().strip()
        )
        logging.info(f"Using docker version:\n{docker_version_output}\n")

        buildx_version_output = (
            common.check_output_with_log(["docker", "buildx", "version"])
            .decode()
            .strip()
        )
        logging.info(f"Using buildx version {buildx_version_output}")

        # check if builder already exists.
        ls_output = (
            common.check_output_with_log(["docker", "buildx", "ls"]).decode().strip()
        )

        if buildx_builder_name not in ls_output:
            # Build new buildx builder
            logging.info(f"Create new buildx builder instance '{buildx_builder_name}'.")
            common.run_command(
                [
                    "docker",
                    "buildx",
                    "create",
                    # This option is important, without it the image won't be pushed to the local registry.
                    "--driver-opt=network=host",
                    "--name",
                    buildx_builder_name,
                ]
            )

        # Use builder.
        logging.info(f"Use buildx builder instance '{buildx_builder_name}'.")
        common.run_command(
            [
                "docker",
                "buildx",
                "use",
                buildx_builder_name,
            ]
        )

        logging.info("Build base image.")

        base_image_tag_suffix = (
            self.base_image_deployment_step.python_image_suffix
        )

        base_image_name = f"agent_base_image:{base_image_tag_suffix}"

        if self.use_test_version:
            logging.info("Build testing image version.")
            base_image_name = f"{base_image_name}-testing"

        registry = self.registry or ""
        tags = self.tags or ["latest"]

        if not os.path.isfile(self.dockerfile_path):
            raise ValueError(f"File path {self.dockerfile_path} doesn't exist")

        tag_options = []

        image_names = type(self).RESULT_IMAGE_NAMES[:]
        for image_name in image_names:

            full_name = image_name

            if self.user:
                full_name = f"{self.user}/{full_name}"

            if registry:
                full_name = f"{registry}/{full_name}"

            for tag in tags:
                tag_options.append("-t")

                full_name_with_tag = f"{full_name}:{tag}"

                tag_options.append(full_name_with_tag)

        command_options = [
            "docker",
            "buildx",
            "build",
            *tag_options,
            "-f",
            str(self.dockerfile_path),
            "--build-arg",
            f"BUILD_TYPE={type(self).PACKAGE_TYPE.value}",
            "--build-arg",
            f"BUILDER_NAME={self.name}",
            "--build-arg",
            f"BASE_IMAGE=localhost:5005/{base_image_name}",
            "--build-arg",
            f"BASE_IMAGE_SUFFIX={base_image_tag_suffix}",
        ]

        if common.DEBUG:
            # If debug, then also specify the debug mode inside the docker build.
            command_options.extend(
                [
                    "--build-arg",
                    "AGENT_BUILD_DEBUG=1",
                ]
            )

        # If we need to push, then specify all platforms.
        if self.push:
            for plat in self.platforms:
                command_options.append("--platform")
                command_options.append(plat)

        if self.use_test_version:
            # Pass special build argument to produce testing image.
            command_options.append("--build-arg")
            command_options.append("MODE=testing")

        if self.push:
            command_options.append("--push")
        else:
            command_options.append("--load")

        command_options.append(str(__SOURCE_ROOT__))

        build_log_message = f"Build images:  {image_names}"
        if self.push:
            build_log_message = f"{build_log_message} and push."
        else:
            build_log_message = (
                f"{build_log_message} and load result image to local docker."
            )

        logging.info(build_log_message)

        # Create container with local image registry. And mount existing registry root with base images.
        registry_container = build_in_docker.LocalRegistryContainer(
            name="agent_image_output_registry",
            registry_port=5005,
            registry_data_path=registry_data_path,
        )

        # Start registry and run build of the final docker image. Build process will refer the the
        # base image in the local registry.
        with registry_container:
            common.run_command(
                command_options,
                # This command runs partially runs the same code, so it would be nice to see the output.
                debug=True,
            )

# CPU architectures or platforms that has to be supported by the Agent docker images,
_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    Architecture.X86_64.as_docker_platform.value,
    Architecture.ARM64.as_docker_platform.value,
    Architecture.ARMV7.as_docker_platform.value,
]

_AGENT_BUILD_DOCKER_PATH = _AGENT_BUILD_PATH / "docker"
_AGENT_BUILD_DEPLOYMENT_STEPS_PATH = _AGENT_BUILD_PATH / "tools/environment_deployments/steps"
_AGENT_BUILD_REQUIREMENTS_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"


class ContainerPackageDistro(enum.Enum):
    DEBIAN = "debian"
    ALPINE = "alpine"

    @property
    def image_suffix(self):
        suffixes = {
            ContainerPackageDistro.DEBIAN: "slim",
            ContainerPackageDistro.ALPINE: "alpine"
        }
        return suffixes[self]


@dataclasses.dataclass
class ContainerPackageTypeInfo:
    package_type: PackageType
    result_image_names: List[str]
    distros: List[ContainerPackageDistro]


_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS = [
    ContainerPackageDistro.DEBIAN,
    ContainerPackageDistro.ALPINE
]

# Here listed all possible types of the containerised agent builds.
_CONTAINER_PACKAGE_INFOS = [
    # An image for running on Docker configured to fetch logs via the file system (the container log
    # directory is mounted to the agent container.)  This is the preferred way of running on Docker.
    # This image is published to scalyr/scalyr-agent-docker-json.
    ContainerPackageTypeInfo(
        package_type=PackageType.DOCKER_JSON,
        result_image_names=["scalyr-agent-docker-json"],
        distros=_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS
    ),
    # An image for running on Docker configured to receive logs from other containers via syslog.
    # This is the deprecated approach (but is still published under scalyr/scalyr-docker-agent for
    # backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog to help
    # with the eventual migration.
    ContainerPackageTypeInfo(
        package_type=PackageType.DOCKER_SYSLOG,
        result_image_names=[
            "scalyr-agent-docker-syslog",
            "scalyr-agent-docker",
        ],
        distros=_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS
    ),
    # An image for running on Docker configured to fetch logs via the Docker API using docker_raw_logs: false
    # configuration option.
    ContainerPackageTypeInfo(
        package_type=PackageType.DOCKER_API,
        result_image_names=["scalyr-agent-docker-api"],
        distros=_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS
    ),
    # An image for running the agent on Kubernetes.
    ContainerPackageTypeInfo(
        package_type=PackageType.K8S,
        result_image_names=["scalyr-k8s-agent"],
        distros=_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS
    ),
    # An image for running the agent on Kubernetes with Kubernetes Open Metrics monitor enabled.
    ContainerPackageTypeInfo(
        package_type=PackageType.K8S_WITH_OPENMETRICS,
        result_image_names=["scalyr-k8s-agent-with-openmetrics-monitor"],
        distros=_DEFAULT_CONTAINER_PACKAGE_POSSIBLE_DISTROS
    )
]

DOCKER_IMAGE_PACKAGE_BUILDERS = {}

for package_info in _CONTAINER_PACKAGE_INFOS:
    for distro in package_info.distros:
        base_docker_image_step = deployments.BuildDockerBaseImageStep(
            name=f"agent-docker-base-image-{distro.value}",
            python_image_suffix=distro.image_suffix,
            platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
        )

        class _ImageBuilder(ContainerImageBuilder):
            NAME = f"{package_info.package_type.value}-{distro.value}"
            PACKAGE_TYPE = package_info.package_type
            CONFIG_PATH = __SOURCE_ROOT__ / "docker" / f"{package_info.package_type.value}-config"
            RESULT_IMAGE_NAMES = package_info.result_image_names[:]
            BASE_IMAGE_BUILDER_STEP = DEPLOYMENT_STEP = base_docker_image_step


        DOCKER_IMAGE_PACKAGE_BUILDERS[_ImageBuilder.NAME] = _ImageBuilder


class BuildTestEnvironment(CacheableBuilder):
    NAME = "test_environment"
    DEPLOYMENT_STEP = deployments.INSTALL_TEST_REQUIREMENT_STEP

