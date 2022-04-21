import enum
import subprocess
from typing import List
import pathlib as pl
import json
import logging

logging.basicConfig(level=logging.DEBUG)

from agent_build.tools import build_step
from agent_build.tools import constants

_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENTS_PATH = _AGENT_BUILD_PATH / "requirement-files"
_AGENT_BUILD_DOCKER_PATH = constants.SOURCE_ROOT / "agent_build" / "docker"

_BASE_IMAGE_NAME_PREFIX = "agent_base_image"


class PrepareBuildxBuilderStep(build_step.PrepareEnvironmentStep):
    def __init__(self):
        super(PrepareBuildxBuilderStep, self).__init__(
            script_path=_AGENT_BUILD_DOCKER_PATH / "prepare_buildx_builder.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
        )


class DockerContainerBaseBuildStep(build_step.ArtifactStep):
    BASE_IMAGE_TAG_SUFFIX: str
    TRACKED_FILE_GLOBS = [
        _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base",
        _AGENT_BUILD_DOCKER_PATH / "install-base-image-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "install-common-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "install-build-dependencies.sh",
        _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base-testing",
        _AGENT_REQUIREMENTS_PATH / "main-requirements.txt",
        _AGENT_REQUIREMENTS_PATH / "compression-requirements.txt",
        _AGENT_REQUIREMENTS_PATH / "docker-image-requirements.txt"
    ]

    def __init__(
            self,
            platforms_to_build: List[str],
    ):

        self.base_image_full_name = f"{_BASE_IMAGE_NAME_PREFIX}:{type(self).BASE_IMAGE_TAG_SUFFIX}"

        base_step = PrepareBuildxBuilderStep()

        super(DockerContainerBaseBuildStep, self).__init__(
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_base_docker_images.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            base_step=base_step,
            additional_settings={
                "PLATFORMS_TO_BUILD": json.dumps(platforms_to_build),
                "RESULT_IMAGE_NAME": self.base_image_full_name,
                "BASE_IMAGE_TAG_SUFFIX": type(self).BASE_IMAGE_TAG_SUFFIX,
                "COVERAGE_VERSION": "4.5.4"
            },
        )


class DebianContainerBaseBuildStep(DockerContainerBaseBuildStep):
    BASE_IMAGE_TAG_SUFFIX = "slim"


class AlpineContainerBaseBuildStep(DockerContainerBaseBuildStep):
    BASE_IMAGE_TAG_SUFFIX = "alpine"


DEBIAN_CONTAINER_BASE_BUILD_STEP = DebianContainerBaseBuildStep(
    platforms_to_build=[
        constants.Architecture.X86_64.as_docker_platform,
        constants.Architecture.ARM64.as_docker_platform,
        constants.Architecture.ARMV7.as_docker_platform
    ]
)

ALPINE_CONTAINER_BASE_BUILD_STEP = AlpineContainerBaseBuildStep(
    platforms_to_build=[
        constants.Architecture.X86_64.as_docker_platform,
        constants.Architecture.ARM64.as_docker_platform,
        constants.Architecture.ARMV7.as_docker_platform
    ]
)

TEST_DEBIAN_CONTAINER_BASE_BUILD_STEP = DebianContainerBaseBuildStep(
    platforms_to_build=[
        constants.Architecture.X86_64.as_docker_platform,
    ]
)

TEST_ALPINE_CONTAINER_BASE_BUILD_STEP = AlpineContainerBaseBuildStep(
    platforms_to_build=[
        constants.Architecture.X86_64.as_docker_platform,
    ]
)


class DockerContainerFinalBuildStep(build_step.ArtifactStep):
    TRACKED_FILE_GLOBS = [
        pl.Path("agent_build/**/*"),
        pl.Path("scalyr_agent/**/*"),
        pl.Path("certs/**/*"),
        pl.Path("VERSION"),
    ]
    def __init__(
            self,
            base_image_step: DockerContainerBaseBuildStep,
            image_build_type: constants.PackageType
    ):

        super(DockerContainerFinalBuildStep, self).__init__(
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_and_push_final_agent_docker_image.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            dependency_steps=[base_image_step],
            additional_settings={
                "BASE_IMAGE_TAG_SUFFIX": base_image_step.BASE_IMAGE_TAG_SUFFIX,
                "BUILD_TYPE": image_build_type.value,
            },
        )

class DockerJsonContainerBuilder(DockerContainerFinalBuildStep):
    """
    An image for running on Docker configured to fetch logs via the file system (the container log
    directory is mounted to the agent container.)  This is the preferred way of running on Docker.
    This image is published to scalyr/scalyr-agent-docker-json.
    """

    PACKAGE_TYPE = constants.PackageType.DOCKER_JSON
    RESULT_IMAGE_NAMES = ["scalyr-agent-docker-json"]

_PACKAGE_TYPE_TO_BUILDER = {
    constants.PackageType.DOCKER_JSON: DockerJsonContainerBuilder
}


def build_final_docker(
        build_type: constants.PackageType,
        base_step: DockerContainerBaseBuildStep,
        testing: bool = False
):
    builder_cls = _PACKAGE_TYPE_TO_BUILDER[build_type]

    builder = builder_cls(
        base_image_step=base_step,
        image_build_type=build_type
    )

    builder.run()

build_final_docker(
    constants.PackageType.DOCKER_JSON,
    base_step=TEST_DEBIAN_CONTAINER_BASE_BUILD_STEP,
)