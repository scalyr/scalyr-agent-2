import enum
import logging
import pathlib as pl
import shutil
import subprocess
import platform
from typing import Dict, Type, List, Union

from agent_build_refactored.utils.constants import SOURCE_ROOT, CpuArch, AGENT_REQUIREMENTS, REQUIREMENTS_DEV_COVERAGE
from agent_build_refactored.utils.docker.common import delete_container
from agent_build_refactored.utils.builder import Builder
from agent_build_refactored.utils.docker.buildx.build import (
    buildx_build,
    OCITarballBuildOutput,
    BuildOutput,
    LocalDirectoryBuildOutput,
    DockerImageBuildOutput
)

from agent_build_refactored.prepare_agent_filesystem import build_linux_fhs_agent_files, add_config

SUPPORTED_ARCHITECTURES = [
    CpuArch.x86_64,
    CpuArch.AARCH64,
    CpuArch.ARMV7,
]

logger = logging.getLogger(__name__)
_PARENT_DIR = pl.Path(__file__).parent


class ImageType(enum.Enum):
    K8S = "k8s"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"


_IMAGE_REGISTRY_NAMES = {
    ImageType.K8S: ["scalyr-k8s-agent"],
    ImageType.DOCKER_JSON: ["scalyr-agent-docker-json"],
    ImageType.DOCKER_SYSLOG: [
        "scalyr-agent-docker-syslog",
        "scalyr-agent-docker",
    ],
    ImageType.DOCKER_API: ["scalyr-agent-docker-api"]
}


class ContainerisedAgentBuilder(Builder):
    """
    Class that builds agent container images.
    """

    BASE_DISTRO: str
    TAG_SUFFIXES: List[str]

    @property
    def dependencies_dir(self) -> pl.Path:
        return self.work_dir / "dependencies"

    @classmethod
    def _build_dependencies(
        cls,
        stage: str,
        architectures: Union[CpuArch, List[CpuArch]],
        output: BuildOutput,
        cache_name: str = None,
        fallback_to_remote_builder: bool = False,
    ):
        """
        Perform build of the dependency Dockerfile. This dockerfile is responsible for building
        multiple dependencies that are used during image build.
        :param stage: Name of a stage to build in a Dockerfile.
        :param architectures: List of architectures to build.
        :param output: Desired output type of the build.
        :param cache_name: Name of the cache. If specified, then the result of a build will be cached.
        :param fallback_to_remote_builder: If True, can be build in a remote docker builder.
        """
        test_requirements = f"{REQUIREMENTS_DEV_COVERAGE}"

        buildx_build(
            dockerfile_path=_PARENT_DIR / "dependencies.Dockerfile",
            context_path=_PARENT_DIR,
            architecture=architectures,
            build_args={
                "BASE_DISTRO": cls.BASE_DISTRO,
                "AGENT_REQUIREMENTS": AGENT_REQUIREMENTS,
                "TEST_REQUIREMENTS": test_requirements,
            },
            stage=stage,
            output=output,
            cache_name=cache_name,
            fallback_to_remote_builder=fallback_to_remote_builder,
        )

    def _build_final_image_base_oci_layout(self):
        """
        Build a special stage in the dependency Dockerfile, which is responsible for building of base image
        of the result image. MUST NOT be cached.
        """

        stage_name = "final_image_base"
        result_image_oci_layout = self.work_dir / stage_name

        self._build_dependencies(
            stage=stage_name,
            architectures=SUPPORTED_ARCHITECTURES[:],
            output=OCITarballBuildOutput(
                dest=result_image_oci_layout,
            ),
        )

        return result_image_oci_layout

    def build_requirement_libs(
            self,
            architecture: CpuArch,
            only_cache: bool = False,
    ):
        """
        Build a special stage in the dependency Dockerfile, which is responsible for
        building agent requirement libs.
        """

        stage_name = "requirement_libs"

        result_dir = self.work_dir / stage_name / architecture.value

        cache_name = f"container-image-build-{self.__class__.BASE_DISTRO}-{stage_name}_{architecture.value}"

        if only_cache:
            output = None
        else:
            output = LocalDirectoryBuildOutput(
                dest=result_dir,
            )

        self._build_dependencies(
            stage=stage_name,
            cache_name=cache_name,
            architectures=architecture,
            output=output,
            fallback_to_remote_builder=True,
        )

        if not only_cache:
            return result_dir

    def generate_final_registry_tags(
        self,
        image_type: ImageType,
        registry: str,
        user: str,
        tags: List[str],
    ) -> List[str]:
        """
        Create list of final tags using permutation of image names, tags and tag suffixes.
        :param registry: Registry hostname
        :param user: Registry username
        :param tags: List of tags.
        :return: List of final tags
        """
        result_names = []

        for image_name in _IMAGE_REGISTRY_NAMES[image_type]:
            for tag in tags:
                for tag_suffix in self.__class__.TAG_SUFFIXES:
                    final_name = f"{registry}/{user}/{image_name}:{tag}{tag_suffix}"
                    result_names.append(final_name)

        return result_names

    def create_agent_filesystem(
        self,
        image_type: ImageType
    ):
        """
        Prepare agent files, like source code and configurations.

        """
        agent_filesystem_dir = self.work_dir / "agent_filesystem"
        build_linux_fhs_agent_files(
            output_path=agent_filesystem_dir,
        )
        # Need to create some docker specific directories.
        pl.Path(agent_filesystem_dir / "var/log/scalyr-agent-2/containers").mkdir()

        # Add config file
        config_name = image_type.value
        config_path = SOURCE_ROOT / "docker" / f"{config_name}-config"
        add_config(config_path, agent_filesystem_dir / "etc/scalyr-agent-2")

        agent_package_dir = agent_filesystem_dir / "usr/share/scalyr-agent-2/py/scalyr_agent"

        # Remove unneeded third party requirement libs and keep only the tcollector library
        shutil.rmtree(agent_package_dir / "third_party_python2")
        shutil.rmtree(agent_package_dir / "third_party_tls")
        third_party_lis_root = agent_package_dir / "third_party"
        for third_party_lib in third_party_lis_root.iterdir():
            if third_party_lib.name == "tcollector":
                continue
            if third_party_lib.is_dir():
                shutil.rmtree(third_party_lib)
            if third_party_lib.is_file():
                third_party_lib.unlink()

        # Remove caches
        for pycache_dir in self.work_dir.rglob("__pycache__"):
            shutil.rmtree(pycache_dir)

        # Also change shebang in the agent_main file to python3, since all images fully switched to it.
        agent_main_path = agent_package_dir / "agent_main.py"
        agent_main_content = agent_main_path.read_text()
        new_agent_main_content = agent_main_content.replace("#!/usr/bin/env python", "#!/usr/bin/env python3", 1)
        agent_main_path.write_text(new_agent_main_content)
        return agent_filesystem_dir

    def _build(
        self,
        image_type: ImageType,
        output: BuildOutput,
        architectures: List[CpuArch],
    ):
        """
        Build final image in the form that is specified in the output argument.
        :param image_type: Type of the image.
        :param output: Build output info
        :param architectures: List of architectures to build.
        :return:
        """
        final_image_base_oci_layout_dir = self._build_final_image_base_oci_layout()

        agent_filesystem_dir = self.create_agent_filesystem(image_type=image_type)

        requirements_libs_contexts = {}
        for requirements_architecture in architectures:
            build_target_name = _arch_to_docker_build_target_folder(
                arch=requirements_architecture,
            )

            context_full_name = f"requirement_libs_{build_target_name}_context"

            requirement_libs_dir = self.build_requirement_libs(
                architecture=requirements_architecture,
            )

            requirements_libs_contexts[context_full_name] = str(requirement_libs_dir)

        buildx_build(
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            context_path=_PARENT_DIR,
            architecture=architectures,
            build_args={
                "BASE_DISTRO": self.__class__.BASE_DISTRO,
                "IMAGE_TYPE": image_type.value
            },
            build_contexts={
                "base_image": f"oci-layout:///{final_image_base_oci_layout_dir}",
                "agent_filesystem": str(agent_filesystem_dir),
                **requirements_libs_contexts,
            },
            output=output,
        )

    def build_and_load_docker_image(
        self,
        image_type: ImageType,
        result_image_name: str,
    ):
        """
        Builds single arch image (architecture matches with system) and load to the current docker images list
        :param image_type: Type of the image.
        :param result_image_name: Name of the image.
        """
        self._build(
            image_type=image_type,
            output=DockerImageBuildOutput(
                name=result_image_name,
            ),
            architectures=[_current_cpu_arch]
        )
        return result_image_name

    def build_oci_tarball(
        self,
        image_type: ImageType,
        output_dir: pl.Path = None,
    ):
        """
        Build image in the form of the OCI tarball
        """

        result_tarball = self.result_dir / f"{image_type.value}-{self.__class__.NAME}.tar"

        self._build(
            image_type=image_type,
            output=OCITarballBuildOutput(
                dest=result_tarball,
                extract=False,
            ),
            architectures=SUPPORTED_ARCHITECTURES[:]
        )

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                result_tarball,
                output_dir,
            )

        return result_tarball

    def publish(
        self,
        image_type: ImageType,
        tags: List[str],
        existing_oci_layout_dir: pl.Path = None,
        registry_username: str = None,
        registry_password: str = None,
        no_verify_tls: bool = False,
    ):
        """
        Publish image
        :param image_type: Type of image
        :param tags: list of tags
        :param existing_oci_layout_dir: Path to existing image OCI tarball. If exists, it will publish image from this
            tarball. If not new image will be built inplace.
        :param registry_username: Registry login
        :param registry_password: Registry password
        :param no_verify_tls: Disable certificate validation when pushing the image.
        :return:
        """
        if existing_oci_layout_dir:
            oci_layer = existing_oci_layout_dir
        else:
            oci_layer = self.build_oci_tarball(image_type=image_type)

        container_name = "agent_image_publish_skopeo"

        delete_container(
            container_name=container_name,
        )

        # use skopeo tool to copy image.
        # also use it from container so we don't have to rly on a local installation.
        cmd_args = [
            "docker",
            "run",
            "-i",
            "--rm",
            f"--name={container_name}",
            "--net=host",
            f"-v={oci_layer}:/tmp/oci_layout.tar",
            "quay.io/skopeo/stable:latest",
            "copy",
            "--all",
        ]

        if not registry_password:
            cmd_args.append(
                "--dest-no-creds",
            )
        else:
            cmd_args.append(
                f"--dest-creds={registry_username}:{registry_password}"
            )

        if no_verify_tls:
            cmd_args.append(
                "--dest-tls-verify=false",
            )

        delete_container(
            container_name=container_name,
        )

        for tag in tags:
            logger.info(f"Publish image '{tag}'")
            subprocess.run(
                [
                    *cmd_args,
                    "oci-archive:/tmp/oci_layout.tar",
                    f"docker://{tag}",
                ],
                check=True,

            )

        delete_container(
            container_name=container_name,
        )


def _arch_to_docker_build_target_folder(arch: CpuArch):
    if arch == CpuArch.x86_64:
        return "linux_amd64_"
    elif arch == CpuArch.AARCH64:
        return "linux_arm64_"
    elif arch == CpuArch.ARMV7:
        return "linux_arm_v7"


# Create all image builder classes and make them available from this global collection.
ALL_CONTAINERISED_AGENT_BUILDERS: Dict[str, Type[ContainerisedAgentBuilder]] = {}


for base_distro in ["ubuntu", "alpine"]:
    tag_suffixes = [f"-{base_distro}"]
    if base_distro == "ubuntu":
        tag_suffixes.append("")

    name = base_distro

    class _ContainerisedAgentBuilder(ContainerisedAgentBuilder):
        NAME = name
        BASE_DISTRO = base_distro
        TAG_SUFFIXES = tag_suffixes[:]

    ALL_CONTAINERISED_AGENT_BUILDERS[name] = _ContainerisedAgentBuilder


def _get_current_machine_architecture():
    machine = platform.machine()

    if machine in ["x86_64"]:
        return CpuArch.x86_64
    if machine in ["aarch64"]:
        return CpuArch.AARCH64
    if machine in ["armv7l"]:
        return CpuArch.ARMV7

    # Add more CPU architectures if needed.
    raise Exception("unknown CPU")


_current_cpu_arch = _get_current_machine_architecture()