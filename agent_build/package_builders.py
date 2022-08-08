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
import logging
import pathlib as pl
import pydoc
import tarfile
import abc
import shutil
import time
import sys
import stat
import os
from typing import List, Type, Tuple, Dict

from agent_build.tools import constants
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker
from agent_build.tools.build_in_docker import LocalRegistryContainer
from agent_build.tools import common
from agent_build.tools.common import check_call_with_log
from agent_build.tools.constants import Architecture, PackageType
from agent_build.tools.environment_deployments.deployments import ShellScriptDeploymentStep, DeploymentStep, CacheableBuilder, EnvironmentShellScriptStep, ArtifactShellScriptStep
from agent_build.prepare_agent_filesystem import build_linux_lfs_agent_files, get_install_info, add_config
from agent_build.tools.constants import SOURCE_ROOT, DockerPlatform, DockerPlatformInfo
from agent_build.tools.common import check_output_with_log
from agent_build.tools.common import shlex_join

log = logging.getLogger(__name__)

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent


_AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"


_REL_DEPLOYMENT_STEPS_PATH = pl.Path("agent_build/tools/environment_deployments/steps")
_REL_AGENT_BUILD_DOCKER_PATH = pl.Path("agent_build/docker")


_DEPLOYMENT_BUILD_BASE_IMAGE_STEP = (
    _AGENT_BUILD_PATH / "tools/environment_deployments/steps/build_base_docker_image"
)
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"


# class BuildDockerBaseImageStep(ShellScriptDeploymentStep):
#     """
#     This deployment step is responsible for the building of the base image of the agent docker images.
#     It runs shell script that builds that base image and pushes it to the local registry that runs in container.
#     After push, registry is shut down, but it's data root is preserved. This step puts this
#     registry data root to the output of the deployment, so the builder of the final agent docker image can access this
#     output and fetch base images from registry root (it needs to start another registry and mount existing registry
#     root).
#     """
#
#     def __init__(
#         self,
#         name: str,
#         python_image_suffix: str,
#         platforms: List[str]
#     ):
#         self.python_image_suffix = python_image_suffix
#         self.platforms = platforms
#
#         super(BuildDockerBaseImageStep, self).__init__(
#             name=name,
#             architecture=Architecture.UNKNOWN,
#             script_path=_DEPLOYMENT_BUILD_BASE_IMAGE_STEP / f"{self.python_image_suffix}.sh",
#             tracked_file_globs=[
#                  _AGENT_BUILD_PATH / "docker/Dockerfile.base",
#                 # and helper lib for base image builder.
#                 _DEPLOYMENT_BUILD_BASE_IMAGE_STEP / "build_base_images_common_lib.sh",
#                 # .. and requirement files.
#                 _AGENT_REQUIREMENT_FILES_PATH / "docker-image-requirements.txt",
#                 _AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt",
#                 _AGENT_REQUIREMENT_FILES_PATH / "main-requirements.txt",
#             ],
#             environment_variables={
#                 "TO_BUILD_PLATFORMS": ",".join(platforms)
#             },
#             cacheable=True
#         )

class ContainerImageBaseDistro(enum.Enum):
    DEBIAN = "debian"
    ALPINE = "alpine"

    @property
    def as_python_image_suffix(self):
        suffixes = {
            ContainerImageBaseDistro.DEBIAN: "slim",
            ContainerImageBaseDistro.ALPINE: "alpine"
        }
        return suffixes[self]


class BaseImageBuilderStep(ArtifactShellScriptStep):
    def __init__(
            self,
            name: str,
            python_base_image: str,
            base_distro: ContainerImageBaseDistro,
            image_platform: DockerPlatformInfo
    ):

        self.python_base_image = python_base_image
        self.base_distro = base_distro
        self.image_platform = image_platform

        platform_dashed_str = image_platform.to_dashed_str

        self.base_image_result_name = name
        self.base_image_result_image_name_with_tag = f"{name}:{platform_dashed_str}"
        self.result_image_tarball_name = f"{name}-{platform_dashed_str}.tar"

        super(BaseImageBuilderStep, self).__init__(
            name=f"{name}-{platform_dashed_str}",
            script_path="agent_build/docker/build_base_image.sh",
            tracked_file_globs=[
                _AGENT_BUILD_PATH / "docker/base.Dockerfile",
                _AGENT_BUILD_PATH / "docker/install-base-dependencies.sh",
                _AGENT_BUILD_PATH / "docker/install-python-libs.sh",
                _AGENT_BUILD_PATH / "docker/install-python-libs-build-dependencies.sh",
                _AGENT_REQUIREMENT_FILES_PATH / "docker-image-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "main-requirements.txt",
            ],
            environment_variables={
                "PYTHON_BASE_IMAGE": self.python_base_image,
                "DISTRO_NAME": self.base_distro.value,
                "RESULT_IMAGE_TARBALL_NAME": self.result_image_tarball_name,
                "PLATFORM": str(self.image_platform),
                "COVERAGE_VERSION": "4.5.4"
            },
            cacheable=True,
            pre_build_in_cicd=True,
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
    ALTERNATIVE_IMAGE_NAMES: List[str] = []

    RESULT_IMAGE_TAG: List[str]
    PYTHON_BASE_IMAGE: str
    BASE_PLATFORM_BUILDER_STEPS: List[BaseImageBuilderStep]

    def __init__(
            self,
            registry: str = None,
            tags: List[str] = None,
            user: str = None,
            push: bool = False,
            platforms: List = None,
            only_filesystem_tarball: str = None,
            image_output_path: str = None,
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

        self.use_test_version = use_test_version
        self.registry = registry
        self.tags = tags or []
        self.user = user
        self.push = push

        self.image_output_path = image_output_path and pl.Path(image_output_path)

        self.only_filesystem_tarball = only_filesystem_tarball and pl.Path(only_filesystem_tarball)
        if self.only_filesystem_tarball:
            self.only_filesystem_tarball = pl.Path(only_filesystem_tarball)

        platforms = platforms
        if platforms is None:
            self.base_platform_builder_steps = type(self).BASE_PLATFORM_BUILDER_STEPS
            #self.platforms = self.base_platform_builder_steps.platforms
        else:
            #self.platforms = platforms
            self.base_platform_builder_steps = []
            for plat in platforms:
                for step in type(self).BASE_PLATFORM_BUILDER_STEPS:
                    if str(step.image_platform) == str(plat):
                        self.base_platform_builder_steps.append(step)
                        break

        super(ContainerImageBuilder, self).__init__(
            required_steps=self.base_platform_builder_steps
        )

        self._package_root_path = self.output_path / "package_root"

    # @property
    # def name(self) -> str:
    #     # Container builders are special since we have an instance per Dockerfile since different
    #     # Dockerfile represents a different builder
    #     return self._name

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

    @classmethod
    def get_final_result_image_name(cls) -> str:
        return f"{cls.RESULT_IMAGE_NAME}:{cls.RESULT_IMAGE_TAG}"

    @classmethod
    def get_final_alternative_names(cls) -> List[str]:
        result = []
        for name in cls.ALTERNATIVE_IMAGE_NAMES:
            result.append(f"{name}:{cls.RESULT_IMAGE_TAG}")
        return result

    @classmethod
    def get_result_image_tarball_name(cls):
        file_name = cls.get_final_result_image_name().replace(":", "-")
        return f"{file_name}.tar"

    @property
    def result_image_tarball_path(self) -> pl.Path:
        return self.output_path / type(self).get_result_image_tarball_name()

    def _build(self, locally: bool = False):
        """
        Combine all platform specific base images into one final multi-arch image.
        """

        if self.only_filesystem_tarball:
            self.build_filesystem_tarball()
            return

        platforms_options = []

        # Since docker buildx builder can not use local docker images as base images,
        # we push them and then pull from the local registry.
        with LocalRegistryContainer(
                name=f"base-images-registry-debian",
                registry_port=5050
        ):
            for base_arch_step in type(self).BASE_PLATFORM_BUILDER_STEPS:
                # Load image from a particular platform from the tarball
                image_path = base_arch_step.output_directory / base_arch_step.result_image_tarball_name
                load_output = check_output_with_log([
                    "docker", "load", "-i", str(image_path)
                ]).decode().strip()

                image_id = load_output.split(":")[-1]

                # Tar loaded image with normal name.
                registry_image_name = f"localhost:5050/{base_arch_step.base_image_result_image_name_with_tag}"
                check_call_with_log([
                    "docker", "tag", image_id, registry_image_name
                ])

                # Push it to local registry.
                check_call_with_log([
                    "docker", "push", registry_image_name
                ])

                platforms_options.extend([
                    "--platform",
                    str(base_arch_step.image_platform)
                ])

            # Build OCI tarball with agent's final image.
            check_call_with_log([
                "docker",
                "buildx",
                "build",
                *platforms_options,
                "--build-arg",
                f"PYTHON_BASE_IMAGE={type(self).PYTHON_BASE_IMAGE}",
                "--build-arg",
                f"BASE_IMAGE_NAME=localhost:5050/{base_arch_step.base_image_result_name}",
                "--build-arg",
                f"BUILDER_FQDN={type(self).get_fully_qualified_name()}",
                "--build-arg",
                f"IMAGE_TYPE_STAGE_NAME={type(self).IMAGE_TYPE_STAGE_NAME}",
                "-f",
                str(SOURCE_ROOT / "agent_build/docker/final.Dockerfile"),
                "--output",
                f"type=oci,dest={self.result_image_tarball_path}",
                str(SOURCE_ROOT)
            ])

        if self.image_output_path:
            target_path = self.image_output_path / self.result_image_tarball_path.name
            log.info(f"Saving result image tarball to '{target_path}'")
            shutil.copy(
                self.result_image_tarball_path,
                self.image_output_path
            ),


_AGENT_BUILD_DOCKER_PATH = _AGENT_BUILD_PATH / "docker"
_AGENT_BUILD_DEPLOYMENT_STEPS_PATH = _AGENT_BUILD_PATH / "tools/environment_deployments/steps"
_AGENT_BUILD_REQUIREMENTS_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"


# CPU architectures or platforms that has to be supported by the Agent docker images,
_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    DockerPlatform.AMD64.value
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
    ALTERNATIVE_IMAGE_NAMES = ["scalyr-agent-docker"]


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


_BASE_IMAGE_PLATFORM_BUILDER_STEPS = collections.defaultdict(dict)
_DISTRO_BUILDERS = collections.defaultdict(list)


def create_distro_specific_image_builders(builder_cls: Type[ContainerImageBuilder]):
    """
    Helper function which creates distro-specific image builder classes from the base agent image builder class.
    For example if builder is for docker-json image then it will produce builder for docker-json-debian,
        docker-json-alpine, etc.
    :param builder_cls: Base image builder class.
    """

    global _BASE_IMAGE_PLATFORM_BUILDER_STEPS

    for base_distro in ContainerImageBaseDistro:
        base_image_arch_builder_steps = []
        result_image_name = f"agent-base-image-{base_distro.value}"
        python_base_image = f"python:3.8.13-{base_distro.as_python_image_suffix}"
        for plat in _AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS:

            if plat in _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro]:
                base_platform_step = _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro][plat]
            else:
                base_platform_step = BaseImageBuilderStep(
                    name=result_image_name,
                    python_base_image=python_base_image,
                    base_distro=base_distro,
                    image_platform=plat
                )
                _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro][plat] = base_platform_step

            base_image_arch_builder_steps.append(base_platform_step)

        if base_distro == ContainerImageBaseDistro.DEBIAN:
            result_image_tag = "latest"
        else:
            result_image_tag = base_distro.value

        class _BaseImageBuilder(builder_cls):
            BUILDER_NAME = f"{builder_cls.BUILDER_NAME}-{base_distro.value}"
            PYTHON_BASE_IMAGE = python_base_image
            RESULT_IMAGE_TAG = result_image_tag
            REQUIRED_STEPS = BASE_PLATFORM_BUILDER_STEPS = base_image_arch_builder_steps[:]

        _BaseImageBuilder.assign_fully_qualified_name(
            class_name=builder_cls.__name__,
            class_name_suffix=base_distro.value,
            module_name=__name__
        )
        _DISTRO_BUILDERS[base_distro].append(_BaseImageBuilder)


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
DOCKER_IMAGE_BUILDERS: Dict[str, Type[ContainerImageBuilder]] = {}
for base_distro, builders in _DISTRO_BUILDERS.items():
    for builder in builders:
        if builder.BUILDER_NAME in DOCKER_IMAGE_BUILDERS:
            raise ValueError(f"Image builder name {builder.BUILDER_NAME} already exists, please rename is.")
        DOCKER_IMAGE_BUILDERS[builder.BUILDER_NAME] = builder

#
# DOCKER_IMAGE_BULK_BUILDERS = {
#     "bulk-images-debian": ImagesBulkBuilderDebian,
#     "bulk-images-alpine": ImagesBulkBuilderAlpine
# }


if __name__ == '__main__':
    matrix = {
        "include": []
    }

    for builder_name, builder in DOCKER_IMAGE_BUILDERS.items():
        matrix["include"].append({
            "builder-name": builder_name,
            "result-tarball-name": builder.get_result_image_tarball_name(),
            "python-version": "3.8.13",
            "os": "ubuntu-20.04",
        })

    print(json.dumps(matrix))