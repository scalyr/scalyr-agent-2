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
import collections
import dataclasses
import enum
import json
import pathlib as pl
import pydoc
import tarfile
import abc
import shutil
import time
import sys
import stat
import os
import logging
from typing import List, Type, Tuple

from agent_build.tools import constants
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker
from agent_build.tools import common
from agent_build.tools.constants import Architecture, PackageType
from agent_build.tools.environment_deployments.deployments import ShellScriptDeploymentStep, DeploymentStep, CacheableBuilder
from agent_build.prepare_agent_filesystem import build_linux_lfs_agent_files, get_install_info, add_config
from agent_build.tools.constants import SOURCE_ROOT
from agent_build.tools.common import check_output_with_log
from agent_build.tools.common import shlex_join

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent


_AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"


_REL_DEPLOYMENT_STEPS_PATH = pl.Path("agent_build/tools/environment_deployments/steps")
_REL_AGENT_BUILD_DOCKER_PATH = pl.Path("agent_build/docker")


_DEPLOYMENT_BUILD_BASE_IMAGE_STEP = (
    _AGENT_BUILD_PATH / "tools/environment_deployments/steps/build_base_docker_image"
)
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"

class BuildDockerBaseImageStep(ShellScriptDeploymentStep):
    """
    This deployment step is responsible for the building of the base image of the agent docker images.
    It runs shell script that builds that base image and pushes it to the local registry that runs in container.
    After push, registry is shut down, but it's data root is preserved. This step puts this
    registry data root to the output of the deployment, so the builder of the final agent docker image can access this
    output and fetch base images from registry root (it needs to start another registry and mount existing registry
    root).
    """

    def __init__(
        self,
        name: str,
        python_image_suffix: str,
        platforms: List[str]
    ):
        self.python_image_suffix = python_image_suffix
        self.platforms = platforms

        super(BuildDockerBaseImageStep, self).__init__(
            name=name,
            architecture=Architecture.UNKNOWN,
            script_path=_DEPLOYMENT_BUILD_BASE_IMAGE_STEP / f"{self.python_image_suffix}.sh",
            tracked_file_globs=[
                 _AGENT_BUILD_PATH / "docker/Dockerfile.base",
                # and helper lib for base image builder.
                _DEPLOYMENT_BUILD_BASE_IMAGE_STEP / "build_base_images_common_lib.sh",
                # .. and requirement files.
                _AGENT_REQUIREMENT_FILES_PATH / "docker-image-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "main-requirements.txt",
            ],
            environment_variables={
                "TO_BUILD_PLATFORMS": ",".join(platforms)
            },
            cacheable=True
        )


class ContainerImageBuilder(CacheableBuilder):
    """
    The base builder for all docker and kubernetes based images . It builds an executable script in the current working
     directory that will build the container image for the various Docker and Kubernetes targets.
     This script embeds all assets it needs in it so it can be a standalone artifact. The script is based on
     `docker/scripts/container_builder_base.sh`. See that script for information on it can be used."
    """
    # Path to the configuration which should be used in this build.
    CONFIG_PATH: pl.Path = None
    ADDITIONAL_CONFIG_PATHS: List[pl.Path] = None

    BUILDER_NAME: str
    IMAGE_TYPE_STAGE_NAME: str = "common"

    # Name of the result image that goes to dockerhub.
    RESULT_IMAGE_NAME: str

    BASE_IMAGE_BUILDER_STEP: BuildDockerBaseImageStep

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
        self.config_path = type(self).CONFIG_PATH
        self.additional_config_paths = type(self).ADDITIONAL_CONFIG_PATHS or []

        self.dockerfile_path = SOURCE_ROOT / "agent_build/docker/Dockerfile"

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
        )

        add_config(
            base_config_source_path=type(self).CONFIG_PATH,
            output_path=self._package_root_path / "etc/scalyr-agent-2",
            additional_config_paths=type(self).ADDITIONAL_CONFIG_PATHS
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

        full_name = type(self).RESULT_IMAGE_NAME

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
            f"IMAGE_TYPE_STAGE_NAME={type(self).IMAGE_TYPE_STAGE_NAME}",
            "--build-arg",
            f"BUILDER_FQDN={type(self).get_fully_qualified_name()}",
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

        command_options.append(str(SOURCE_ROOT))

        build_log_message = f"Build image:  {full_name}"
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

_AGENT_BUILD_DOCKER_PATH = _AGENT_BUILD_PATH / "docker"
_AGENT_BUILD_DEPLOYMENT_STEPS_PATH = _AGENT_BUILD_PATH / "tools/environment_deployments/steps"
_AGENT_BUILD_REQUIREMENTS_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"


# CPU architectures or platforms that has to be supported by the Agent docker images,
_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    Architecture.X86_64.as_docker_platform.value,
    # Architecture.ARM64.as_docker_platform.value,
    # Architecture.ARMV7.as_docker_platform.value,
]


class DockerJsonContainerBuilder(ContainerImageBuilder):
    BUILDER_NAME = "docker-json"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-json-config"
    RESULT_IMAGE_NAME = "scalyr-agent-docker-json"


class DockerSyslogContainerBuilder(ContainerImageBuilder):
    BUILDER_NAME = PACKAGE_TYPE = "docker-syslog"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-syslog-config"
    # "scalyr-agent-docker",
    RESULT_IMAGE_NAME = "scalyr-agent-docker-syslog"



class DockerApiContainerBuilder(ContainerImageBuilder):
    BUILDER_NAME = "docker-api"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-api-config"
    RESULT_IMAGE_NAME = "scalyr-agent-docker-api"


class K8sContainerBuilder(ContainerImageBuilder):
    BUILDER_NAME = IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config"
    RESULT_IMAGE_NAME = "scalyr-k8s-agent"


class K8sWithOpenmetricsContainerBuilder(ContainerImageBuilder):
    BUILDER_NAME = "k8s-with-openmetrics"
    IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config-with-openmetrics-monitor"
    RESULT_IMAGE_NAME = "scalyr-k8s-agent-with-openmetrics-monitor"


class K8sRestartAgentOnMonitorsDeathBuilder(ContainerImageBuilder):
    BUILDER_NAME = "k8s-restart-agent-on-monitor-death"
    IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config"
    ADDITIONAL_CONFIG_PATHS = [
        SOURCE_ROOT / "docker" / "k8s-config-restart-agent-on-monitor-death"
    ]
    RESULT_IMAGE_NAME = "scalyr-k8s-restart-agent-on-monitor-death"


class ContainerImageBaseDistro(enum.Enum):
    DEBIAN = "debian"
    ALPINE = "alpine"

    @property
    def image_suffix(self):
        suffixes = {
            ContainerImageBaseDistro.DEBIAN: "slim",
            ContainerImageBaseDistro.ALPINE: "alpine"
        }
        return suffixes[self]


# Collection of the agent image base image builder stapes.
_BASE_IMAGES_BUILDER_STEPS = {}

for distro in ContainerImageBaseDistro:
    _BASE_IMAGES_BUILDER_STEPS[distro] = BuildDockerBaseImageStep(
        name=f"agent-docker-base-image-{distro.value}",
        python_image_suffix=distro.image_suffix,
        platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
)

# # Instantiate builder steps for base images.
# BASE_DOCKER_IMAGE_BUILD_STEP_DEBIAN = BuildDockerBaseImageStep(
#     name=f"agent-docker-base-image-debian",
#     python_image_suffix="slim",
#     platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
# )
# BASE_DOCKER_IMAGE_BUILD_STEP_ALPINE = BuildDockerBaseImageStep(
#     name=f"agent-docker-base-image-alpine",
#     python_image_suffix="alpine",
#     platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
# )

# Collection of all agent image builders grouped by base distro (debian, alpine).
_DISTRO_BUILDERS = collections.defaultdict(list)


def create_distro_specific_image_builders(builder_cls: Type[ContainerImageBuilder]):
    """
    Helper function which creates distro-specific image builder classes from the base agent image builder class.
    For example if builder is for docker-json image then it will produce builder for docker-json-debian,
        docker-json-alpine, etc.
    :param builder_cls: Base image builder class.
    """

    global _DISTRO_BUILDERS

    module = sys.modules[__name__]

    for distro in ContainerImageBaseDistro:

        # Create CamelCase distro name suffix for builder class name.
        distro_name_chars = list(distro.value)
        distro_name_chars[0] = distro_name_chars[0].upper()
        distro_camel_case_name = "".join(distro_name_chars)

        builder_class_name = f"{builder_cls.__name__}{distro_camel_case_name}"

        # Since we create those builders dynamically, they won't be able to find their FDQN properly,
        # That's why we cheat a little with specifying FDQN manually.
        # We'll create attribute in this module which will point to this particular builder class,
        # and FQND has to be exactly this new attribute.
        builder_fqnd = f"{module.__name__}.{builder_class_name}"

        class _BuilderClass(builder_cls):
            DISTRO = distro
            BASE_IMAGE_BUILDER_STEP = DEPLOYMENT_STEP = _BASE_IMAGES_BUILDER_STEPS[distro]
            _FULLY_QUALIFIED_NAME = builder_fqnd

        # Add result builder as current module's attribute because that's where the above FDQN has to point.
        setattr(module, builder_class_name, _BuilderClass)

        _DISTRO_BUILDERS[distro].append(_BuilderClass)


create_distro_specific_image_builders(DockerJsonContainerBuilder)
create_distro_specific_image_builders(DockerSyslogContainerBuilder)
create_distro_specific_image_builders(DockerApiContainerBuilder)
create_distro_specific_image_builders(K8sContainerBuilder)
create_distro_specific_image_builders(K8sWithOpenmetricsContainerBuilder)
create_distro_specific_image_builders(K8sRestartAgentOnMonitorsDeathBuilder)


class ImageBulkBuilder(CacheableBuilder):
    """
    This class is mostly for the CI/CD reasons.
    The result image on the CI/Cd is put to local registry and root of that registry is saved as artifact.
    This class build all image of the same base bistro image (aka -debian or -alpine). This can help put all
    images in one registry anf then put that registry as artifact.
    """
    IMAGE_BUILDERS: List[Type[ContainerImageBuilder]]

    def __init__(
        self,
        registry: str = None,
        push: bool = False,
    ):
        self.registry = registry
        self.push = push

        self.image_builders = []
        for image_builder_cls in type(self).IMAGE_BUILDERS:

            image_builder = image_builder_cls(
                registry=self.registry,
                push=self.push
            )
            self.image_builders.append(image_builder)

        super(ImageBulkBuilder, self).__init__(
            required_builders=self.image_builders
        )

    def build(self, locally: bool = False):

        for image_builder in self.image_builders:
            image_builder.build(locally=locally)


# Bulk builder for debian based images.
class ImagesBulkBuilderDebian(ImageBulkBuilder):
    REQUIRED_BUILDER_CLASSES = IMAGE_BUILDERS = _DISTRO_BUILDERS[ContainerImageBaseDistro.DEBIAN][:]


# Bulk builder for alpine based images.
class ImagesBulkBuilderAlpine(ImageBulkBuilder):
    REQUIRED_BUILDER_CLASSES = IMAGE_BUILDERS = _DISTRO_BUILDERS[ContainerImageBaseDistro.ALPINE][:]


# Final collection with all agent image builder classes.
DOCKER_IMAGE_BUILDERS = {}
for distro, builders in _DISTRO_BUILDERS.items():
    for builder in builders:
        if builder.BUILDER_NAME in DOCKER_IMAGE_BUILDERS:
            raise ValueError(f"Image builder name {builder.BUILDER_NAME} already exists, please rename is.")
        DOCKER_IMAGE_BUILDERS[f"{builder.BUILDER_NAME}-{distro.value}"] = builder


DOCKER_IMAGE_BULK_BUILDERS = {
    "bulk-images-debian": ImagesBulkBuilderDebian,
    "bulk-images-alpine": ImagesBulkBuilderAlpine
}


if __name__ == '__main__':
    matrix = {
        "include": []
    }
    for distro in _DISTRO_BUILDERS.keys():
        matrix["include"].append({
            "os": "ubuntu-22.04",
            "python-version": "3.8.13",
            "image-distro": distro.value
        })

    print(json.dumps(matrix))