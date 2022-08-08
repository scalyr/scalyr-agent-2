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
import collections
import enum
import json
import logging
import pathlib as pl
import re
import tarfile
import shutil
import os
from typing import List, Type, Dict

from agent_build.tools.common import LocalRegistryContainer
from agent_build.tools.common import check_call_with_log
from agent_build.tools.runner import Runner, ArtifactRunnerStep
from agent_build.prepare_agent_filesystem import build_linux_lfs_agent_files, add_config
from agent_build.tools.constants import SOURCE_ROOT, DockerPlatform, DockerPlatformInfo
from agent_build.tools.common import check_output_with_log

log = logging.getLogger(__name__)

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

IMAGES_PYTHON_VERSION = "3.8.13"

_AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"
_TEST_REQUIREMENTS_FILE_PATH = _AGENT_REQUIREMENT_FILES_PATH / "testing-requirements.txt"

# Get version of the coverage lib for the test version of the images.
# Parse version from requirements file in order to be in sync with it.
TEST_IMAGE_COVERAGE_VERSION = re.search(
    r"coverage==([\d\.]+)",
    _TEST_REQUIREMENTS_FILE_PATH.read_text()
).group(1)


class ContainerImageBaseDistro(enum.Enum):
    """
    Enum type which represents different distribution types which can be base for our particular images.
    """
    DEBIAN = "debian"
    ALPINE = "alpine"

    @property
    def as_python_image_suffix(self):
        suffixes = {
            ContainerImageBaseDistro.DEBIAN: "slim",
            ContainerImageBaseDistro.ALPINE: "alpine"
        }
        return suffixes[self]


class BaseImagePlatformBuilderStep(ArtifactRunnerStep):
    """
    Runner step which builds one particular platform of the base image for the agent's final docker image.
    This step, as a result, produces tarball with base image for a particular platform/architecture of the final docker
    image. All such images will be used together to build final multi-arch image.
    """
    def __init__(
            self,
            python_base_image: str,
            base_distro: ContainerImageBaseDistro,
            image_platform: DockerPlatformInfo
    ):
        """
        :param python_base_image: Name of the base docker image with python.
        :param base_distro: Distry type of the base image, e.g. debian, alpine.
        :param image_platform: Target platform/architecture of the result base image.
        """

        self.python_base_image = python_base_image
        self.base_distro = base_distro
        self.image_platform = image_platform

        platform_dashed_str = image_platform.to_dashed_str

        self.base_result_image_name = f"agent-base-image-{base_distro.value}"
        self.base_result_image_name_with_tag = f"{self.base_result_image_name }:{platform_dashed_str}"
        self.result_image_tarball_name = f"{self.base_result_image_name }-{platform_dashed_str}.tar"

        super(BaseImagePlatformBuilderStep, self).__init__(
            name=f"{self.base_result_image_name}-{platform_dashed_str}",
            script_path="agent_build/docker/build_base_image.sh",
            tracked_files_globs=[
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
                "COVERAGE_VERSION": TEST_IMAGE_COVERAGE_VERSION
            },
            cacheable=True,
            pre_build_in_cicd=True,
        )


class ContainerImageRunner(Runner):
    """
    The base builder for all docker and kubernetes based images. It builds base images for each particular
        platform/architecture and then use them to build a final multi-arch image.
    """
    # Path to the configuration which should be used in this build.
    CONFIG_PATH: pl.Path = None
    # List of path to additional config directories. Will overwrite existing config files if they already exist.
    ADDITIONAL_CONFIG_PATHS: List[pl.Path] = None

    # Name of the image builder. The build script uses this name.
    BUILDER_NAME: str

    # Name of the stage in the dockerfile which has to be picked for this particular image type.
    # Image types with specialized final docker images (for example k8s, docker-syslog) has to use their own
    # stage name, other has to use the 'common stage.'
    IMAGE_TYPE_STAGE_NAME: str = "common"

    # Name of the result image that goes to dockerhub.
    RESULT_IMAGE_NAME: str

    # List of names under which the image also has to be published to dockerhub.
    ALTERNATIVE_IMAGE_NAMES: List[str] = []

    RESULT_IMAGE_TAG: List[str]

    # Base docker image with python.
    PYTHON_BASE_IMAGE: str

    # List of runner steps where each of them is responsible for one particular platform/architecture.
    BASE_PLATFORM_BUILDER_STEPS: List[BaseImagePlatformBuilderStep]

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
        :param image_output_path: Path where result image tarball has to be stored.
        :param use_test_version: Build a special version of image with additional measuring tools (such as coverage).
            Used only for testing."
        """
        self.config_path = type(self).CONFIG_PATH
        self.additional_config_paths = type(self).ADDITIONAL_CONFIG_PATHS or []

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
        else:
            # If only some platforms are specified, then use only those base image builder steps.
            self.base_platform_builder_steps = []
            for plat in platforms:
                for step in type(self).BASE_PLATFORM_BUILDER_STEPS:
                    if str(step.image_platform) == str(plat):
                        self.base_platform_builder_steps.append(step)
                        break

        super(ContainerImageRunner, self).__init__(
            required_steps=self.base_platform_builder_steps
        )

        self._package_root_path = self.output_path / "package_root"

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

    def _run(self):
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
                # Load image for a particular platform from the tarball
                image_path = base_arch_step.output_directory / base_arch_step.result_image_tarball_name
                load_output = check_output_with_log([
                    "docker", "load", "-i", str(image_path)
                ]).decode().strip()

                image_id = load_output.split(":")[-1]

                # Tag loaded image with normal name.
                registry_image_name = f"localhost:5050/{base_arch_step.base_result_image_name_with_tag}"
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
                f"BASE_IMAGE_NAME=localhost:5050/{base_arch_step.base_result_image_name}",
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
            self.image_output_path.mkdir(exist_ok=True, parents=True)
            shutil.copy2(
                self.result_image_tarball_path,
                self.image_output_path
            ),


# CPU architectures or platforms that has to be supported by the Agent docker images,
_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    DockerPlatform.AMD64.value,
    DockerPlatform.ARM64.value,
    DockerPlatform.ARMV7.value,
]


class DockerJsonContainerBuilder(ContainerImageRunner):
    BUILDER_NAME = "docker-json"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-json-config"
    RESULT_IMAGE_NAME = "scalyr-agent-docker-json"


class DockerSyslogContainerBuilder(ContainerImageRunner):
    BUILDER_NAME = PACKAGE_TYPE = "docker-syslog"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-syslog-config"
    # "scalyr-agent-docker",
    RESULT_IMAGE_NAME = "scalyr-agent-docker-syslog"
    ALTERNATIVE_IMAGE_NAMES = ["scalyr-agent-docker"]


class DockerApiContainerBuilder(ContainerImageRunner):
    BUILDER_NAME = "docker-api"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "docker-api-config"
    RESULT_IMAGE_NAME = "scalyr-agent-docker-api"


class K8sContainerBuilder(ContainerImageRunner):
    BUILDER_NAME = IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config"
    RESULT_IMAGE_NAME = "scalyr-k8s-agent"


class K8sWithOpenmetricsContainerBuilder(ContainerImageRunner):
    BUILDER_NAME = "k8s-with-openmetrics"
    IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config-with-openmetrics-monitor"
    RESULT_IMAGE_NAME = "scalyr-k8s-agent-with-openmetrics-monitor"


class K8sRestartAgentOnMonitorsDeathBuilder(ContainerImageRunner):
    BUILDER_NAME = "k8s-restart-agent-on-monitor-death"
    IMAGE_TYPE_STAGE_NAME = "k8s"
    CONFIG_PATH = SOURCE_ROOT / "docker" / "k8s-config"
    ADDITIONAL_CONFIG_PATHS = [
        SOURCE_ROOT / "docker" / "k8s-config-restart-agent-on-monitor-death"
    ]
    RESULT_IMAGE_NAME = "scalyr-k8s-restart-agent-on-monitor-death"


_BASE_IMAGE_PLATFORM_BUILDER_STEPS = collections.defaultdict(dict)

# Final collection of all docker image builder.
DOCKER_IMAGE_BUILDERS: Dict[str, Type[ContainerImageRunner]] = {}


def create_distro_specific_image_builders(builder_cls: Type[ContainerImageRunner]):
    """
    Helper function which creates distro-specific image builder classes from the base agent image builder class.
    For example if builder is for 'docker-json' image then it will produce builder for docker-json-debian,
        docker-json-alpine, etc.
    :param builder_cls: Base image builder class.
    """

    global _BASE_IMAGE_PLATFORM_BUILDER_STEPS, DOCKER_IMAGE_BUILDERS

    for base_distro in ContainerImageBaseDistro:
        base_image_builder_steps = []
        python_base_image = f"python:{IMAGES_PYTHON_VERSION}-{base_distro.as_python_image_suffix}"

        # Create or reuse base platform/architecture image builder steps.
        for plat in _AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS:
            if plat in _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro]:
                base_platform_step = _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro][plat]
            else:
                base_platform_step = BaseImagePlatformBuilderStep(
                    python_base_image=python_base_image,
                    base_distro=base_distro,
                    image_platform=plat
                )
                _BASE_IMAGE_PLATFORM_BUILDER_STEPS[base_distro][plat] = base_platform_step

            base_image_builder_steps.append(base_platform_step)

        # We use debian image as default/latest.
        if base_distro == ContainerImageBaseDistro.DEBIAN:
            result_image_tag = "latest"
        else:
            result_image_tag = base_distro.value

        # Create builder class for a specialised image.
        class _BaseImageBuilder(builder_cls):
            # Add distro suffix  to a general image builder name.
            BUILDER_NAME = f"{builder_cls.BUILDER_NAME}-{base_distro.value}"
            PYTHON_BASE_IMAGE = python_base_image
            RESULT_IMAGE_TAG = result_image_tag
            REQUIRED_STEPS = BASE_PLATFORM_BUILDER_STEPS = base_image_builder_steps[:]

        # Assign fully qualified name to the result class, so it can be found outside this temporary scope.
        _BaseImageBuilder.assign_fully_qualified_name(
            class_name=builder_cls.__name__,
            module_name=__name__,
            class_name_suffix=base_distro.value,
        )
        if _BaseImageBuilder.BUILDER_NAME in DOCKER_IMAGE_BUILDERS:
            raise ValueError(f"Image builder name {builder.BUILDER_NAME} already exists, please rename is.")
        DOCKER_IMAGE_BUILDERS[_BaseImageBuilder.BUILDER_NAME] = _BaseImageBuilder


# Create distro specific image builders from general builder classes.
create_distro_specific_image_builders(DockerJsonContainerBuilder)
create_distro_specific_image_builders(DockerSyslogContainerBuilder)
create_distro_specific_image_builders(DockerApiContainerBuilder)
create_distro_specific_image_builders(K8sContainerBuilder)
create_distro_specific_image_builders(K8sWithOpenmetricsContainerBuilder)
create_distro_specific_image_builders(K8sRestartAgentOnMonitorsDeathBuilder)


if __name__ == '__main__':
    # We use this module as script in order to generate build job matrix for GitHub Actions.
    matrix = {
        "include": []
    }

    for builder_name, builder in DOCKER_IMAGE_BUILDERS.items():
        matrix["include"].append({
            "builder-name": builder_name,
            "result-tarball-name": builder.get_result_image_tarball_name(),
            "python-version": f"{IMAGES_PYTHON_VERSION}",
            "os": "ubuntu-20.04",
        })

    print(json.dumps(matrix))