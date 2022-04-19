import enum
import subprocess
from typing import List
import pathlib as pl


from agent_build.tools import build_step
from agent_build.tools import constants

_AGENT_BUILD_PATH = constants.SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENTS_PATH = _AGENT_BUILD_PATH / "requirement-files"
_AGENT_BUILD_DOCKER_PATH = constants.SOURCE_ROOT / "agent_build" / "docker"


class DockerContainerBaseBuildStep(build_step.ArtifactStep):
    TRACKED_FILE_GLOBS = [
        _AGENT_BUILD_DOCKER_PATH / "Dockerfile.base-debian",
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
            architecture: constants.Architecture,
            result_image_name: str,
            base_image_tag_suffix: str
    ):
        super(DockerContainerBaseBuildStep, self).__init__(
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_base_docker_images.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            additional_settings={
                "PLATFORM_TO_BUILD": architecture.as_docker_platform.value,
                "RESULT_IMAGE_NAME": result_image_name,
                "BASE_IMAGE_TAG_SUFFIX": base_image_tag_suffix,
                "COVERAGE_VERSION": "4.5.4"
            }
        )


class DockerContainerFinalBuildStep(build_step.ArtifactStep):
    class BasePythonImageDistro(enum.Enum):
        DEBIAN = "slim"
        ALPINE = "alpine"

    PYTHON_BASE_IMAGE_DISTRO: BasePythonImageDistro

    def __init__(
            self,
            supported_architectures: List[constants.Architecture],
    ):

        self._supported_architectures = supported_architectures

        result_image_name = "agent_docker_base_image"

        self._architecture_base_image_steps = {}
        for arch in supported_architectures:
            tag_suffix = type(self).PYTHON_BASE_IMAGE_DISTRO.value
            result_image_name = f"{result_image_name}_{tag_suffix}"

            base_step = DockerContainerBaseBuildStep(
                architecture=arch,
                result_image_name=result_image_name,
                base_image_tag_suffix=tag_suffix
            )

            self._architecture_base_image_steps[result_image_name] = base_step

        super(DockerContainerFinalBuildStep, self).__init__(
            script_path=_AGENT_BUILD_DOCKER_PATH / "build_agent_final_docker_images.py",
            build_root=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/agent_build_output"),
            additional_settings={},
            dependency_steps=list(self._architecture_base_image_steps.values())
        )

    def run(self):
        super(DockerContainerFinalBuildStep, self).run()

        from agent_build.tools import common

        for base_image_name, base_image_step in self._architecture_base_image_steps.items():
            base_image_registry_output = base_image_step.output_directory / "output_registry"

            base_image_registry_container = common.LocalRegistryContainer(
                name="base_image_registry",
                registry_port=5000,
                registry_data_path=base_image_registry_output
            )
            base_image_registry_container.start()


class BasePythonImageDistro(enum.Enum):
    DEBIAN = "slim"
    ALPINE = "alpine"

def build(
    supported_architectures: List[constants.Architecture],
    base_python_image_distro: BasePythonImageDistro
):

    base_result_image_name = "agent_docker_base_image"

    from agent_build.tools import common

    result_registry_container = common.LocalRegistryContainer(
        "result_image_registry",
        registry_port=5002,
        registry_data_path=pl.Path("/Users/arthur/work/agents/scalyr-agent-2/build_test")
    )

    result_registry_container.start()

    architecture_base_image_steps = {}
    for arch in supported_architectures:
        tag_suffix = base_python_image_distro.value
        base_result_image_name = f"{base_result_image_name}-{tag_suffix}-{arch.as_docker_platform.value}"

        base_step = DockerContainerBaseBuildStep(
            architecture=arch,
            result_image_name=base_result_image_name,
            base_image_tag_suffix=tag_suffix
        )

        base_step.run()

        base_image_registry_output = base_step.output_directory / "output_registry"

        base_image_registry_container = common.LocalRegistryContainer(
            name="base_image_registry",
            registry_port=5001,
            registry_data_path=base_image_registry_output
        )
        base_image_registry_container.start()

        full_base_image_name = f"localhost:5001/{base_result_image_name}"

        subprocess.check_call([
            "docker", "pull", full_base_image_name
        ])

        full_base_image_result_registry_name = f"localhost:5002/{base_result_image_name}"

        subprocess.check_call([
            "docker", "tag", full_base_image_name, full_base_image_result_registry_name
        ])
        subprocess.check_call([
            "docker",
            "push",
            full_base_image_result_registry_name
        ])

        base_image_registry_container.kill()

build(
    supported_architectures=[
        constants.Architecture.X86_64
    ],
    base_python_image_distro=BasePythonImageDistro.DEBIAN
)