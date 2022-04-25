import argparse
import collections
import dataclasses
import enum
import functools
import subprocess
import pathlib as pl
import json
import logging
import sys
from typing import List, Dict, Type, ClassVar

logging.basicConfig(level=logging.DEBUG)

from agent_build.tools import build_step
from agent_build.tools import constants, common
from agent_build.tools.build_step import StepCICDSettings, BuildStep, FinalStep
from agent_build.tools.constants import AGENT_BUILD_OUTPUT

_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENTS_PATH = _AGENT_BUILD_PATH / "requirement-files"
_AGENT_BUILD_DOCKER_PATH = constants.SOURCE_ROOT / "agent_build" / "docker"

_BASE_IMAGE_NAME_PREFIX = "agent_base_image"

_BUILDX_BUILDER_NAME = "agent_image_buildx_builder"

ALL_CACHEABLE_STEPS = []


class PrepareBuildxBuilderStep(build_step.SimpleBuildStep):
    def __init__(self):
        super(PrepareBuildxBuilderStep, self).__init__(
            name="prepare_buildx_builder",
            global_steps_collection=ALL_CACHEABLE_STEPS
        )

    def _run(self):
        # Prepare buildx builder, first check if there is already existing builder.
        builders_list_output = subprocess.check_output([
            "docker",
            "buildx",
            "ls"
        ]).decode().strip()

        # Builder is not found, create new one.
        if _BUILDX_BUILDER_NAME not in builders_list_output:
            subprocess.check_call([
                "docker",
                "buildx",
                "create",
                "--driver-opt=network=host",
                "--name",
                _BUILDX_BUILDER_NAME
            ])

        # Use needed builder.
        subprocess.check_call([
            "docker",
            "buildx",
            "use",
            _BUILDX_BUILDER_NAME
        ])


class DockerBaseImageDistroType(enum.Enum):
    """
    Type of the distribution which is used as base for the agent image.
    """
    DEBIAN = "debian"
    ALPINE = "alpine"


# Mapping of base image distributions types to actual docker images from the Dockerhub.
_DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME = {
    DockerBaseImageDistroType.DEBIAN: "python:3.8.12-slim",
    DockerBaseImageDistroType.ALPINE: "python:3.8.12-alpine"
}


class DockerContainerBaseBuildStep(build_step.ScriptBuildStep):
    TRACKED_FILE_GLOBS = [
        _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base",
        _AGENT_BUILD_DOCKER_PATH / "install-base-image-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "install-base-image-common-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "install-base-image-build-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "install-base-image-rust.sh",
        _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base-testing",
        _AGENT_REQUIREMENTS_PATH / "main-requirements.txt",
        _AGENT_REQUIREMENTS_PATH / "compression-requirements.txt",
        _AGENT_REQUIREMENTS_PATH / "docker-image-requirements.txt"
    ]

    def __init__(
            self,
            platforms_to_build: List[str],
            base_image_distro_type: DockerBaseImageDistroType,
    ):
        base_step = PrepareBuildxBuilderStep()
        self.base_image_distro_type = base_image_distro_type
        self.platforms_to_build = platforms_to_build

        super(DockerContainerBaseBuildStep, self).__init__(
            name="agent_docker_base_image_build",
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_base_docker_images.py",
            base_step=base_step,
            is_dependency_step=True,
            additional_settings={
                "PLATFORMS_TO_BUILD": json.dumps(platforms_to_build),
                "RESULT_IMAGE_NAME": f"{_BASE_IMAGE_NAME_PREFIX}:{base_image_distro_type.value}",
                "PYTHON_BASE_IMAGE_TYPE": base_image_distro_type.value,
                "PYTHON_BASE_IMAGE_NAME": _DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME[base_image_distro_type],
                "COVERAGE_VERSION": "4.5.4"
            },
            ci_cd_settings=StepCICDSettings(
                cacheable=True,
                prebuilt_in_separate_job=True
            ),
            global_steps_collection=ALL_CACHEABLE_STEPS
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
    constants.Architecture.X86_64.as_docker_platform,
    # constants.Architecture.ARM64.as_docker_platform,
    # constants.Architecture.ARMV7.as_docker_platform
]

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


class ImageBuild(FinalStep):
    BASE_IMAGE_DISTRO_TYPE: ClassVar[DockerBaseImageDistroType]
    DOCKER_IMAGE_TYPE: ClassVar[DockerImageType]
    RESULT_IMAGE_NAMES: List[str]

    def __init__(
        self,
        registry: str = None,
        user: str = None,
        tags: List[str] = None,
        push: bool = False,
        platforms_to_build: List[str] = None
    ):
        self.registry = registry
        self.user = user
        self.tags = tags or []
        self.push = push

        if not platforms_to_build:
            self._base_image_step = _AGENT_BASE_IMAGE_BUILDER_STEPS[type(self).BASE_IMAGE_DISTRO_TYPE]
            self.platforms_to_build = self._base_image_step.platforms_to_build
        else:
            # If custom platforms are specified, then create a new instance of base image builder step with that
            # platforms. That's mainly needed for testing.
            self.platforms_to_build = platforms_to_build
            self._base_image_step = DockerContainerBaseBuildStep(
                platforms_to_build=self.platforms_to_build,
                base_image_distro_type=type(self).BASE_IMAGE_DISTRO_TYPE
            )

        # Also add step that prepares docker's buildx builder.
        # This is needed when the base image step is got from cache and skipped, but we still need
        # to configure the buildx builder to build the final image.
        prepare_buildx_builder_step = PrepareBuildxBuilderStep()
        super(ImageBuild, self).__init__(
            used_steps=[
                prepare_buildx_builder_step,
                self._base_image_step
            ]
        )

    def _run(self):
        """
        Build final agent docker image by using base image whish has to be built in the base image step.
        """
        base_image_registry_path = self._base_image_step.output_directory / "output_registry"
        base_image_registry_port = 5003
        base_image_name = f"agent_base_image:{self._base_image_step.base_image_distro_type.name.lower()}"
        base_image_full_name = f"localhost:{base_image_registry_port}/{base_image_name}"

        tag_options = []
        for image_name in _DOCKER_IMAGE_TYPES_TO_IMAGE_RESULT_NAMES[type(self).DOCKER_IMAGE_TYPE]:

            full_name = image_name

            if self.user:
                full_name = f"{self.user}/{full_name}"

            if self.registry:
                full_name = f"{self.registry}/{full_name}"

            for tag in self.tags:
                tag_options.extend([
                    "-t",
                    f"{full_name}:{tag}"
                ])

        platforms_options = []
        for p in self.platforms_to_build:
            platforms_options.extend([
                "--platform",
                p
            ])

        command_options = [
            "docker",
            "buildx",
            "build",
            *tag_options,
            "-f",
            str(constants.SOURCE_ROOT / "agent_build/docker/Dockerfile"),
            "--build-arg",
            f"PYTHON_BASE_IMAGE={_DOCKER_IMAGE_DISTRO_TO_IMAGE_NAME[self._base_image_step.base_image_distro_type]}",
            "--build-arg",
            f"DOCKER_IMAGE_TYPE={type(self).DOCKER_IMAGE_TYPE.value}",
            "--build-arg",
            f"BASE_IMAGE={base_image_full_name}",
            *platforms_options,
            str(constants.SOURCE_ROOT)
        ]

        if self.push:
            command_options.append("--push")

        base_image_registry = common.LocalRegistryContainer(
            name="agent_base_registry",
            registry_port=base_image_registry_port,
            registry_data_path=base_image_registry_path
        )

        with base_image_registry:
            subprocess.check_call([
                *command_options
            ])


# Final collection of the docker image builds, where key - unique name of the build
# and value - build class.
IMAGE_BUILDS: Dict[str, Type[ImageBuild]] = {}


# Dynamically enumerate all possible base images and image types to produce
# final builds.
for distro_type in DockerBaseImageDistroType:
    for docker_image_type in DockerImageType:
        class Build(ImageBuild):
            BASE_IMAGE_DISTRO_TYPE = distro_type
            DOCKER_IMAGE_TYPE = docker_image_type
            RESULT_IMAGE_NAMES = _DOCKER_IMAGE_TYPES_TO_IMAGE_RESULT_NAMES[docker_image_type]

        build_name = f"{docker_image_type.value}-{distro_type.value}"
        IMAGE_BUILDS[build_name] = Build


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_step_subparser = subparsers.add_parser("run-step")

    cacheable_steps = {s.id: s for s in ALL_CACHEABLE_STEPS}
    run_step_subparser.add_argument("id", choices=cacheable_steps.keys())
    run_step_subparser.add_argument(
        "--build-root_dir",
        dest="build_root_dir",
        required=False
    )

    args = parser.parse_args()

    if args.command == "run-step":
        if args.id not in cacheable_steps:
            print(f"Step with id {args.id} is not found.", file=sys.stderr)
            exit(1)

        step = cacheable_steps[args.id]
        if args.build_root_dir:
            build_root_path = pl.Path(args.build_root_dir)
        else:
            build_root_path = AGENT_BUILD_OUTPUT

        step.run(
            build_root=build_root_path
        )

