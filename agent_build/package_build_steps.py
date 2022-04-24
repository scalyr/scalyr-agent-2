import dataclasses
import enum
import functools
import subprocess
import pathlib as pl
import json
import logging
from typing import List, Dict, Type

logging.basicConfig(level=logging.DEBUG)

from agent_build.tools import build_step
from agent_build.tools import constants, common
from agent_build.tools.build_step import StepCICDSettings, BuildStep

_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENTS_PATH = _AGENT_BUILD_PATH / "requirement-files"
_AGENT_BUILD_DOCKER_PATH = constants.SOURCE_ROOT / "agent_build" / "docker"

_BASE_IMAGE_NAME_PREFIX = "agent_base_image"

_BUILDX_BUILDER_NAME = "agent_image_buildx_builder"


class PrepareBuildxBuilderStep(build_step.SimpleBuildStep):
    def __init__(self):
        super(PrepareBuildxBuilderStep, self).__init__(
            name="PrepareBuildxBuilder",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
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


class PythonBaseImage(enum.Enum):
    DEBIAN = "python:3.8.12-slim"
    ALPINE = "python:3.8.12-alpine"


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
            python_base_image: PythonBaseImage,
    ):
        base_step = PrepareBuildxBuilderStep()

        super(DockerContainerBaseBuildStep, self).__init__(
            name="AgentDockerBaseImageBuild",
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_base_docker_images.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            base_step=base_step,
            is_dependency_step=True,
            additional_settings={
                "PLATFORMS_TO_BUILD": json.dumps(platforms_to_build),
                "RESULT_IMAGE_NAME": f"{_BASE_IMAGE_NAME_PREFIX}:{python_base_image.name.lower()}",
                "PYTHON_BASE_IMAGE_TYPE": python_base_image.name.lower(),
                "PYTHON_BASE_IMAGE_NAME": python_base_image.value,
                "COVERAGE_VERSION": "4.5.4"
            },
            ci_cd_settings=StepCICDSettings(
                prebuilt_in_separate_job=True
            )
        )


_DEFAULT_DOCKER_IMAGES_PLATFORMS = [
    constants.Architecture.X86_64.as_docker_platform,
    constants.Architecture.ARM64.as_docker_platform,
    constants.Architecture.ARMV7.as_docker_platform
]


_DEBIAN_BASE_CONTAINER_BUILD_STEP = DockerContainerBaseBuildStep(
    platforms_to_build=_DEFAULT_DOCKER_IMAGES_PLATFORMS,
    python_base_image=PythonBaseImage.DEBIAN
)


_BASE_IMAGE_BUILD_STEPS = {}
_TEST_BASE_IMAGE_BUILD_STEPS = {}

for python_base_image in PythonBaseImage:
    _BASE_IMAGE_BUILD_STEPS[python_base_image] = DockerContainerBaseBuildStep(
        platforms_to_build=[
            constants.Architecture.X86_64.as_docker_platform,
            constants.Architecture.ARM64.as_docker_platform,
            constants.Architecture.ARMV7.as_docker_platform
        ],
        python_base_image=python_base_image
    )
    _TEST_BASE_IMAGE_BUILD_STEPS[python_base_image] = DockerContainerBaseBuildStep(
        platforms_to_build=[
            constants.Architecture.X86_64.as_docker_platform
        ],
        python_base_image=python_base_image
    )


_TESTING_DOCKER_IMAGES_PLATFORMS = [
    constants.Architecture.X86_64.as_docker_platform,
]


class DockerImageType(enum.Enum):
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"
    K8S = "k8s"


class DockerContainerFinalBuildStep(build_step.SimpleBuildStep):
    TRACKED_FILE_GLOBS = [
        pl.Path("agent_build/**/*"),
        pl.Path("scalyr_agent/**/*"),
        pl.Path("certs/**/*"),
        pl.Path("VERSION"),
    ]
    DOCKER_IMAGE_TYPE: DockerImageType
    PYTHON_BASE_IMAGE: PythonBaseImage
    RESULT_IMAGE_NAMES: List[str]

    def __init__(
            self,
            registry: str = None,
            user: str = None,
            tags: List[str] = None,
            push: bool = False,
            testing: bool = False,
    ):

        self._build_base_image_step = type(self).get_base_image_builder_step(
            testing=testing
        )

        self._docker_image_type = type(self).DOCKER_IMAGE_TYPE
        self._python_base_image = type(self).PYTHON_BASE_IMAGE
        self._registry = registry
        self._user = user
        self._tags = tags
        self._to_push = push
        self._testing = testing

        super(DockerContainerFinalBuildStep, self).__init__(
            name="AgentDockerImageBuild",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            dependency_steps=[self._build_base_image_step],
            additional_settings={},
            ci_cd_settings=StepCICDSettings(
                # This step should not be cached in CI/CD
                cached=False
            )
        )

    @classmethod
    def get_base_image_builder_step(cls, testing: bool):
        if testing:
            base_images = _BASE_IMAGE_BUILD_STEPS
        else:
            base_images = _TEST_BASE_IMAGE_BUILD_STEPS

        return base_images[cls.PYTHON_BASE_IMAGE]


    def _run(self):

        base_image_registry_path = self._build_base_image_step.output_directory / "output_registry"
        base_image_registry_port = 5003
        base_image_name = f"agent_base_image:{self._python_base_image.name.lower()}"
        base_image_full_name = f"localhost:{base_image_registry_port}/{base_image_name}"

        tag_options = []
        for image_name in type(self).RESULT_IMAGE_NAMES:

            full_name = image_name

            if self._user:
                full_name = f"{self._user}/{full_name}"

            if self._registry:
                full_name = f"{self._registry}/{full_name}"

            for tag in self._tags:
                tag_options.extend([
                    "-t",
                    f"{full_name}:{tag}"
                ])

        command_options = [
            "docker",
            "buildx",
            "build",
            *tag_options,
            "-f",
            str(constants.SOURCE_ROOT / "agent_build/docker/Dockerfile"),
            "--build-arg",
            f"PYTHON_BASE_IMAGE={self._python_base_image.value}",
            "--build-arg",
            f"DOCKER_IMAGE_TYPE={self._docker_image_type.value}",
            "--build-arg",
            f"BASE_IMAGE={base_image_full_name}",
            str(constants.SOURCE_ROOT)
        ]

        if self._to_push:
            command_options.append("--push")

        # result_registry = common.LocalRegistryContainer(
        #     name="result_registry_container",
        #     registry_port=5004,
        #     registry_data_path=self._temp_output_directory
        # )

        base_image_registry = common.LocalRegistryContainer(
            name="agent_base_registry",
            registry_port=base_image_registry_port,
            registry_data_path=base_image_registry_path
        )

        with base_image_registry:
            subprocess.check_call([
                *command_options
            ])


class DockerJsonContainerBuildStep(DockerContainerFinalBuildStep):
    DOCKER_IMAGE_TYPE = DockerImageType.DOCKER_JSON
    RESULT_IMAGE_NAMES = ["scalyr-agent-docker-json"]


class DockerSyslogContainerBuildStep(DockerContainerFinalBuildStep):
    DOCKER_IMAGE_TYPE = DockerImageType.DOCKER_SYSLOG
    RESULT_IMAGE_NAMES = [
        "scalyr-agent-docker-syslog",
        "scalyr-agent-docker",
    ]


class DockerApiContainerBuildStep(DockerContainerFinalBuildStep):
    DOCKER_IMAGE_TYPE = DockerImageType.DOCKER_API
    RESULT_IMAGE_NAMES = ["scalyr-agent-docker-api"]


class K8sContainerBuilderStep(DockerContainerBaseBuildStep):
    DOCKER_IMAGE_TYPE = DockerImageType.K8S
    RESULT_IMAGE_NAMES = ["scalyr-k8s-agent"]


class DockerJsonContainerBuildStepDebian(DockerApiContainerBuildStep):
    PYTHON_BASE_IMAGE = PythonBaseImage.DEBIAN


_DOCKER_IMAGE_BUILDERS_CLASSES: Dict[DockerImageType, Type[DockerContainerFinalBuildStep]] = {
    DockerImageType.DOCKER_JSON: DockerJsonContainerBuildStep,
    DockerImageType.DOCKER_SYSLOG: DockerSyslogContainerBuildStep,
    DockerImageType.DOCKER_API: DockerApiContainerBuildStep,
    DockerImageType.K8S: K8sContainerBuilderStep,
}


DOCKER_IMAGE_BUILDERS: Dict[str, Type[DockerContainerFinalBuildStep]] = {}


for docker_image_type in DockerImageType:
    for python_base_image in PythonBaseImage:
        builder_name = f"{docker_image_type.value}-{python_base_image.name.lower()}"
        _docker_image_builder_cls = _DOCKER_IMAGE_BUILDERS_CLASSES[docker_image_type]

        class DockerImageBuilder(_docker_image_builder_cls):
            PYTHON_BASE_IMAGE = python_base_image

        DOCKER_IMAGE_BUILDERS[builder_name] = DockerImageBuilder




def run_docker_image_builder(
    builder: BuildStep,
    registry: str = None,
    user: str = None,
    tags:List[str] = None,
    push: bool = False,
    testing: bool = False
):

    builder_step_cls = DOCKER_IMAGE_BUILDERS[image_builder_name]
    builder = builder_step_cls(
        registry=registry,
        user=user,
        tags=tags or [],
        push=push,
        testing=testing
    )

    builder.run()
