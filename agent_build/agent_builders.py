"""
This module defines builders for each of the Agent's distribution.

Each type of the agent distribution has to be built by a particular builder. Basically those builders are subclasses of
the 'Builder' abstract class in the  'tools.builder' module, and the build process has to be performed in its overridden
``_run`` method. Some part of the build can be moved to a separate 'BuilderStep' to be able to cache that part of the
build using CI/CD.


"""

import enum
import subprocess
import json
import logging
import pathlib as pl

from typing import List, Dict, Type, ClassVar, Union

import agent_build.tools.common

logging.basicConfig(level=logging.DEBUG)

from agent_build.tools import common
from agent_build.tools.builder import Builder
from agent_build.tools.builder import EnvironmentBuilderStep, ArtifactBuilderStep, BuilderStep
from agent_build.tools.common import Architecture


# Final collection of the docker image builders, where key - unique name of the build
# and value - build class.
IMAGE_BUILDERS: Dict[str, Type['ImageBuilder']] = {}

# Global collection of all cacheable builder steps. It is needed to be able to find and to execute particular step from
# CI/CD
ALL_CACHEABLE_STEPS: Dict[str, BuilderStep] = {}


def get_builders_all_cacheable_steps(builder_cls: Type[Builder]):
    result = {}
    for s in builder_cls.CACHEABLE_STEPS:
        if s.id not in ALL_CACHEABLE_STEPS:
            continue

        result[s.id] = s

    return list(result.values())


BUILDERS_PYTHON_VERSION = "3.8.13"

COVERAGE_VERSION_FOR_TESTING_IMAGE = "4.5.4"

# CPU architectures or platforms that has to be supported by the Agent docker images,
AGENT_DOCKER_IMAGE_SUPPORTED_ARCHITECTURES = [
    Architecture.X86_64,
    Architecture.ARM64,
    Architecture.ARMV7,
]


_AGENT_BUILD_PATH = agent_build.tools.common.SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENTS_PATH = _AGENT_BUILD_PATH / "requirement-files"
_AGENT_BUILD_DOCKER_PATH = agent_build.tools.common.SOURCE_ROOT / "agent_build" / "docker"

#_BASE_IMAGE_NAME_PREFIX = "agent_base_image"


class DockerBaseImageDistroType(enum.Enum):
    """
    Type of the distribution which is used as base for the agent image.
    """
    DEBIAN = "debian"
    ALPINE = "alpine"


# Mapping of base image distributions types to actual docker images from the Dockerhub.
_DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME = {
    DockerBaseImageDistroType.DEBIAN: f"python:{BUILDERS_PYTHON_VERSION}-slim",
    DockerBaseImageDistroType.ALPINE: f"python:{BUILDERS_PYTHON_VERSION}-alpine"
}

def create_docker_buildx_builder():
    """
    Prepare buildx builder with a special network configuration which is required to build the image.
    """

    buildx_build_name = "agent_image_buildx_builder"

    # First check if buider with that name already exists.
    builders_list_output = subprocess.check_output([
        "docker",
        "buildx",
        "ls"
    ]).decode().strip()

    # Builder is not found, create new one.
    if buildx_build_name not in builders_list_output:
        subprocess.check_call([
            "docker",
            "buildx",
            "create",
            "--driver-opt=network=host",
            "--name",
            buildx_build_name
        ])

    # Use needed builder.
    subprocess.check_call([
        "docker",
        "buildx",
        "use",
        buildx_build_name
    ])



class DockerContainerBaseBuildStep(ArtifactBuilderStep):
    """

    """

    def __init__(
            self,
            platforms_to_build: List[str],
            base_image_distro_type: DockerBaseImageDistroType,
    ):
        """
        :param platforms_to_build: List of docker platforms that this base image has to support.
        :param base_image_distro_type: One of the py:class:`DockerBaseImageDistroType` type,
            to specify which distribution to use as a base for this image.
        """

        self.base_image_distro_type = base_image_distro_type
        self.platforms_to_build = platforms_to_build
        self.base_image_result_name = f"agent_base_image:{base_image_distro_type.value}"

        super(DockerContainerBaseBuildStep, self).__init__(
            name="agent_docker_base_image_build",
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_base_docker_images.py",
            additional_settings={
                "PLATFORMS_TO_BUILD": json.dumps(platforms_to_build),
                "RESULT_IMAGE_NAME": self.base_image_result_name,
                "PYTHON_BASE_IMAGE_NAME": _DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME[base_image_distro_type],
                "COVERAGE_VERSION": COVERAGE_VERSION_FOR_TESTING_IMAGE
            },
            tracked_file_globs=[
                _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base",
                _AGENT_BUILD_DOCKER_PATH / "install-base-image-build-dependencies.sh",
                _AGENT_BUILD_DOCKER_PATH / "install-base-image-rust.sh",
                _AGENT_BUILD_DOCKER_PATH / "install-base-image-agent-dependencies.sh",
                _AGENT_BUILD_DOCKER_PATH / "install-base-image-dependencies.sh",
                _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base-testing",
                _AGENT_REQUIREMENTS_PATH / "main-requirements.txt",
                _AGENT_REQUIREMENTS_PATH / "compression-requirements.txt",
                _AGENT_REQUIREMENTS_PATH / "docker-image-requirements.txt"
            ],
        )

    def run(self, build_root: pl.Path):
        # Also prepare docker buildx builder.
        create_docker_buildx_builder()
        super(DockerContainerBaseBuildStep, self).run(
            build_root=build_root
        )


class DockerImageType(enum.Enum):
    """
    Type of the result agent docker image.
    """
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"
    K8S = "k8s"


# Set of docker platforms that are supported by prod image.
_PROD_DOCKER_IMAGES_PLATFORMS = [
    arch.as_docker_platform
    for arch in AGENT_DOCKER_IMAGE_SUPPORTED_ARCHITECTURES
]

# Mapping of the agent image base step for the base distro type.
_AGENT_BASE_IMAGE_BUILDER_STEPS = {
    DockerBaseImageDistroType.DEBIAN: DockerContainerBaseBuildStep(
        platforms_to_build=_PROD_DOCKER_IMAGES_PLATFORMS,
        base_image_distro_type=DockerBaseImageDistroType.DEBIAN
    ),
    DockerBaseImageDistroType.ALPINE: DockerContainerBaseBuildStep(
        platforms_to_build=_PROD_DOCKER_IMAGES_PLATFORMS,
        base_image_distro_type=DockerBaseImageDistroType.ALPINE
    )
}
ALL_CACHEABLE_STEPS.update({s.id:s for s in _AGENT_BASE_IMAGE_BUILDER_STEPS.values()})


# Names of the result dockerhub agent images according to a type of the image.
_DOCKER_IMAGE_TYPES_TO_IMAGE_RESULT_NAMES = {
    DockerImageType.DOCKER_JSON: ["scalyr-agent-docker-json"],
    DockerImageType.DOCKER_SYSLOG: [
            "scalyr-agent-docker-syslog",
            "scalyr-agent-docker",
        ],
    DockerImageType.DOCKER_API: ["scalyr-agent-docker-api"],
    DockerImageType.K8S: ["scalyr-k8s-agent"]
}


class ImageBuilder(Builder):
    """
    A builder class that builds agent docker images. Builders classes of the final, specific docker images has to
    be inherited from this class with specifying its class attributes.
    """

    # Type of the final agent docker image.
    DOCKER_IMAGE_TYPE: ClassVar[DockerImageType]

    # List of names of the final images that has to be pushed to a dockerhub.
    RESULT_IMAGE_NAMES: List[str]

    # Class of the builder step, that is responsible for building of the base image.
    AGENT_BASE_IMAGE_BUILDER_STEP: DockerContainerBaseBuildStep

    def __init__(
        self,
        registry: str = None,
        user: str = None,
        tags: List[str] = None,
        push: bool = False,
        platforms_to_build: List[str] = None,
        testing: bool = False
    ):
        self.registry = registry
        self.user = user
        self.tags = tags or []
        self.push = push
        self._testing = testing

        base_image_step = type(self).AGENT_BASE_IMAGE_BUILDER_STEP

        if platforms_to_build:
            # If custom platforms are specified, then create a new instance of base image builder step with that
            # platforms. That's needed only for testing to skip the build of the non-native architectures in CircleCi
            self.platforms_to_build = platforms_to_build
            self._base_image_step = DockerContainerBaseBuildStep(
                platforms_to_build=platforms_to_build,
                base_image_distro_type=base_image_step.base_image_distro_type
            )
        else:
            self._base_image_step = base_image_step
            self.platforms_to_build = self._base_image_step.platforms_to_build

        super(ImageBuilder, self).__init__()

    def run(self, build_root: pl.Path):
        """
        Build final agent docker image by using base image which has to be built in the base image step.
        """

        self._set_build_root(build_root)

        self._base_image_step.run(build_root=build_root)

        base_image_registry_path = self._base_image_step.output_directory / "output_registry"
        base_image_registry_port = 5003
        base_image_name = self._base_image_step.base_image_result_name
        base_image_full_name = f"localhost:{base_image_registry_port}/{base_image_name}"

        if self._testing:
            base_image_full_name = f"{base_image_full_name}-testing"

        test_tag_options = []
        tag_options = []
        for image_name in type(self).RESULT_IMAGE_NAMES:

            full_name = image_name

            if self.user:
                full_name = f"{self.user}/{full_name}"

            if self.registry:
                full_name = f"{self.registry}/{full_name}"

            for tag in self.tags:
                image_and_tag = f"{full_name}:{tag}"
                tag_options.extend([
                    "-t",
                    image_and_tag
                ])
                if self._testing:
                    test_tag_options.extend([
                        "-t",
                        f"{image_and_tag}-testing"
                    ])

        platforms_options = []
        for p in self.platforms_to_build:
            platforms_options.extend(["--platform", p])

        command_options = [
            "docker",
            "buildx",
            "build",
            *tag_options,
            "-f",
            str(agent_build.tools.common.SOURCE_ROOT / "agent_build/docker/Dockerfile.final"),
            "--build-arg",
            f"PYTHON_BASE_IMAGE={_DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME[self._base_image_step.base_image_distro_type]}",
            "--build-arg",
            f"DOCKER_IMAGE_TYPE={type(self).DOCKER_IMAGE_TYPE.value}",
            "--build-arg",
            f"BASE_IMAGE={base_image_full_name}",
            *platforms_options,
            str(agent_build.tools.common.SOURCE_ROOT)
        ]

        if self.push:
            command_options.append("--push")
        else:
            command_options.append("--load")

        base_image_registry = common.LocalRegistryContainer(
            name="agent_base_registry",
            registry_port=base_image_registry_port,
            registry_data_path=base_image_registry_path
        )

        with base_image_registry:
            subprocess.check_call([
                *command_options
            ])
            # If this is a testing build then build another - test image upon production image using special Dockerfile.
            if self._testing:
                test_build_command_options = ["docker"]
                if self.push:
                    test_build_command_options.append("buildx")

                test_build_command_options.extend([
                    "build",
                    *test_tag_options,
                    "-f",
                    str(agent_build.tools.common.SOURCE_ROOT / "agent_build/docker/Dockerfile.final-testing"),
                    "--build-arg",
                    f"BASE_IMAGE={tag_options[1]}"
                ])

                if self.push:
                    test_build_command_options.extend(platforms_options)
                    test_build_command_options.append("--push")

                test_build_command_options.append(str(agent_build.tools.common.SOURCE_ROOT))

                common.check_call_with_log(
                    test_build_command_options
                )


# Dynamically enumerate all possible base images and image types to produce
# final builds.
for distro_type in DockerBaseImageDistroType:
    for docker_image_type in DockerImageType:

        build_name = f"{docker_image_type.value}-{distro_type.value}"
        build_base_image_step = _AGENT_BASE_IMAGE_BUILDER_STEPS[distro_type]

        class FinalImageBuilder(ImageBuilder):
            NAME = build_name
            AGENT_BASE_IMAGE_BUILDER_STEP = build_base_image_step
            CACHEABLE_STEPS = [build_base_image_step]
            DOCKER_IMAGE_TYPE = docker_image_type
            RESULT_IMAGE_NAMES = _DOCKER_IMAGE_TYPES_TO_IMAGE_RESULT_NAMES[docker_image_type]

        IMAGE_BUILDERS[build_name] = FinalImageBuilder


# Step that installs all dependencies for testing
deploy_test_environment_step = EnvironmentBuilderStep(
    name="deploy_test_environment",
    script_path=_AGENT_BUILD_PATH / "deploy_test_environment.sh",
    tracked_file_globs=[
        _AGENT_REQUIREMENTS_PATH / "*.txt"
    ]
)
ALL_CACHEABLE_STEPS[deploy_test_environment_step.id] = deploy_test_environment_step


# Builder class which installs all requirements to CI/CD in order to perform tests.
class TestEnvironmentBuilder(Builder):
    CACHEABLE_STEPS = [deploy_test_environment_step]
    NAME = "test-environment"


ALL_BUILDERS:  Dict[str, Union[Type['Builder'], Type['ImageBuilder']]] = {}
ALL_BUILDERS.update(IMAGE_BUILDERS)
ALL_BUILDERS[TestEnvironmentBuilder.NAME] = TestEnvironmentBuilder
