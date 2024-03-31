# Copyright 2014-2023 Scalyr Inc.
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


import enum
import logging
import pathlib as pl
import shutil
import subprocess
import platform
from typing import Dict, Type, List, Set

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

_SUPPORTED_ARCHITECTURES = [
    CpuArch.x86_64,
    CpuArch.AARCH64,
    CpuArch.ARMV7,
]

logger = logging.getLogger(__name__)
_PARENT_DIR = pl.Path(__file__).parent
_BASE_IMAGES_DIR = _PARENT_DIR / "base_images"


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
    AGENT_REQUIREMENTS_EXCLUDE = []

    def __init__(self, base_image):
        super(ContainerisedAgentBuilder, self).__init__()

        self._already_build_requirements: Set[CpuArch] = set()
        self.__base_image = base_image

    @property
    def __build_args(self) -> Dict[str, str]:
        build_args = {
            "BASE_IMAGE": self.__base_image
        }

        return build_args

    @property
    def _common_cache_name(self):
        return f"agent_image_build_{self.__class__.BASE_DISTRO}"

    def _build_base_image_dockerfile(
            self,
            stage: str,
            architectures: List[CpuArch] = None,
            cache_name: str = None,
            output: BuildOutput = None
    ):

        buildx_build(
            dockerfile_path=_BASE_IMAGES_DIR / f"{self.__class__.BASE_DISTRO}.Dockerfile",
            context_path=_BASE_IMAGES_DIR,
            architectures=architectures,
            stage=stage,
            cache_name=cache_name,
            output=output,
            capture_output=True,
            build_args=self.__build_args
        )

    def __agent_requirements(self):
        return "\n".join([
            dependency
            for dependency in AGENT_REQUIREMENTS.split("\n")
            if not any(
                dependency.startswith(excluded) for excluded in self.__class__.AGENT_REQUIREMENTS_EXCLUDE
            )
        ])

    def build_requirement_libs(
            self,
            architecture: CpuArch,
            only_cache: bool = False,
    ):
        """
        Build a special stage in the dependency Dockerfile, which is responsible for
        building agent requirement libs.
        """

        work_name = f"requirement_libs_{architecture.value}"
        result_dir = self.work_dir / work_name

        # do not build requirements for the same architecture if it is already built.
        if architecture in self._already_build_requirements:
            return result_dir

        base_image_work_name = f"{work_name}_base_image"
        base_image_oci_layout_dir = self.work_dir / f"{base_image_work_name}"
        base_image_cache_name = f"{self._common_cache_name}_{base_image_work_name}"

        self._build_base_image_dockerfile(
            architectures=[architecture],
            stage="dependencies_build_base",
            cache_name=base_image_cache_name,
            output=OCITarballBuildOutput(
                dest=base_image_oci_layout_dir
            )
        )

        cache_name = f"{self._common_cache_name}_{work_name}"

        if only_cache:
            output = None
        else:
            output = LocalDirectoryBuildOutput(
                dest=result_dir,
            )

        test_requirements = f"{REQUIREMENTS_DEV_COVERAGE}"

        buildx_build(
            dockerfile_path=_PARENT_DIR / "dependencies.Dockerfile",
            context_path=_PARENT_DIR,
            architectures=[architecture],
            build_args={
                "AGENT_REQUIREMENTS": self.__agent_requirements(),
                "TEST_REQUIREMENTS": test_requirements,
            },
            build_contexts={
                "extended_base": f"oci-layout:///{base_image_oci_layout_dir}",
            },
            output=output,
            cache_name=cache_name,
            fallback_to_remote_builder=True,
        )

        if not only_cache:
            self._already_build_requirements.add(architecture)
            return result_dir

    def get_image_registry_names(self, image_type: ImageType):
        """Get list of names that this image has to have in the result registry"""
        return _IMAGE_REGISTRY_NAMES[image_type]

    def get_supported_architectures(self):
        return _SUPPORTED_ARCHITECTURES[:]

    def generate_final_registry_tags(
        self,
        image_type: ImageType,
        registry: str,
        name_prefix: str,
        tags: List[str],
    ) -> List[str]:
        """
        Create list of final tags using permutation of image names, tags and tag suffixes.
        :param image_type: Type of the image
        :param registry: Registry hostname
        :param name_prefix: Prefix to the image name.
        :param tags: List of tags.
        :return: List of final tags
        """
        result_names = []

        for image_name in self.get_image_registry_names(image_type=image_type):
            for tag in tags:
                for tag_suffix in self.__class__.TAG_SUFFIXES:
                    final_name = f"{registry}/{name_prefix}/{image_name}:{tag}{tag_suffix}"
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
        architectures: List[CpuArch] = None,
    ):
        """
        Build final image in the form that is specified in the output argument.
        :param image_type: Type of the image.
        :param output: Build output info
        :param architectures: List of architectures to build.
        :return:
        """

        architectures = architectures or self.get_supported_architectures()

        agent_filesystem_dir = self.create_agent_filesystem(image_type=image_type)

        runtime_base_image_oci_layer_dir = self.work_dir / "runtime_image_base"

        self._build_base_image_dockerfile(
            architectures=architectures,
            stage="runtime_base",
            output=OCITarballBuildOutput(
                dest=runtime_base_image_oci_layer_dir
            )
        )

        requirements_libs_contexts = {}
        build_args = {
            "BASE_DISTRO": self.__class__.BASE_DISTRO,
            "IMAGE_TYPE": image_type.value
        }

        for req_arch in architectures:
            build_target_name = _arch_to_docker_build_target_name(
                architecture=req_arch,
            )

            context_full_name = f"requirement_libs_{build_target_name}_context"

            requirement_libs_dir = self.build_requirement_libs(
                architecture=req_arch,
            )
            requirements_libs_contexts[context_full_name] = str(requirement_libs_dir)

        # If there's only one architecture to build, then docker, inconveniently, does not provide
        # its build-it arguments, so we have to provide them manually.
        if len(architectures) == 1:
            target_arch, target_variant = _arch_to_target_arch_and_variant(architectures[0])
            build_args.update({
                "TARGETOS": "linux",
                "TARGETARCH": target_arch,
                "TARGETVARIANT": target_variant,
            })

        buildx_build(
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            context_path=_PARENT_DIR,
            architectures=architectures,
            build_args=build_args,
            build_contexts={
                "base": f"oci-layout:///{runtime_base_image_oci_layer_dir}",
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
            architectures=[_current_cpu_arch],
        )
        return result_image_name

    def build_oci_tarball(
        self,
        image_type: ImageType,
        architectures: List[CpuArch] = None,
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
            architectures=architectures
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
        existing_oci_layout_tarball: pl.Path = None,
        registry_username: str = None,
        registry_password: str = None,
        no_verify_tls: bool = False,
    ):
        """
        Publish an image. Since we can publish image from the OCI layout tarball. We can not use just a normal
            'docker push' command, and we have to use tools that can also operate with OCI image archives.
            We use skopeo in this case.
        :param image_type: Type of image
        :param tags: list of tags
        :param existing_oci_layout_tarball: Path to existing image OCI tarball. If exists, it will publish image from this
            tarball. If not new image will be built inplace.
        :param registry_username: Registry login
        :param registry_password: Registry password
        :param no_verify_tls: Disable certificate validation when pushing the image.
        :return:
        """
        if existing_oci_layout_tarball:
            oci_layout_tarball = existing_oci_layout_tarball
        else:
            oci_layout_tarball = self.build_oci_tarball(image_type=image_type)

        if not oci_layout_tarball.exists():
            raise Exception("OCI layout tarball does not exists.")

        container_name = f"agent_image_publish_skopeo_{self.name}_{image_type.value}"

        delete_container(
            container_name=container_name,
        )

        # use skopeo tool to copy image.
        # also use it from container, so we don't have to rly on a local installation.
        # We also do not use mounting because on some docker environments, this feature may be unavailable,
        # so we just create a container first and then copy the tarball.
        cmd_args = [
            "docker",
            "create",
            "--rm",
            f"--name={container_name}",
            "--net=host",
            "quay.io/skopeo/stable:v1.13.2",
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

            try:
                # Create the container, copy tarball into it and start.
                subprocess.run(
                    [
                        *cmd_args,
                        f"oci-archive:/tmp/{oci_layout_tarball.name}",
                        f"docker://{tag}",
                    ],
                    check=True,
                )

                subprocess.run(
                    [
                        "docker",
                        "cp",
                        str(oci_layout_tarball),
                        f"{container_name}:/tmp/{oci_layout_tarball.name}"
                    ]
                )
                subprocess.run(
                    [
                        "docker",
                        "start",
                        "-i",
                        container_name,
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                logger.exception(
                    f"Subprocess call failed. Stderr: {(e.stderr or b'').decode()}"
                )
                raise
            finally:
                delete_container(
                    container_name=container_name,
                )


def _arch_to_docker_build_target_name(architecture: CpuArch):

    target_arch, target_variant = _arch_to_target_arch_and_variant(architecture)
    return f"linux_{target_arch}_{target_variant}"


def _arch_to_target_arch_and_variant(architecture: CpuArch):
    if architecture == CpuArch.x86_64:
        return "amd64", ""
    elif architecture == CpuArch.AARCH64:
        return "arm64", ""
    elif architecture == CpuArch.ARMV7:
        return "arm", "v7"


# Create all image builder classes and make them available from this global collection.
CONTAINERISED_AGENT_BUILDERS: Dict[str, Type[ContainerisedAgentBuilder]] = {}

requirement_libs_exclude = {
    "alpine": ["orjson", "lz4", "zstandard"]
}

for base_distro in ["ubuntu", "alpine"]:
    tag_suffixes = [f"-{base_distro}"]
    if base_distro == "ubuntu":
        tag_suffixes.append("")

    name = base_distro

    class _ContainerisedAgentBuilder(ContainerisedAgentBuilder):
        NAME = name
        BASE_DISTRO = base_distro
        TAG_SUFFIXES = tag_suffixes[:]
        AGENT_REQUIREMENTS_EXCLUDE = requirement_libs_exclude.get(base_distro, [])


    CONTAINERISED_AGENT_BUILDERS[name] = _ContainerisedAgentBuilder


def _get_current_machine_architecture():
    machine = platform.machine()

    if machine in ["x86_64"]:
        return CpuArch.x86_64
    if machine in ["aarch64", "arm64"]:
        return CpuArch.AARCH64
    if machine in ["armv7l"]:
        return CpuArch.ARMV7

    # Add more CPU architectures if needed.
    raise Exception(f"unknown CPU {machine}")


_current_cpu_arch = _get_current_machine_architecture()


def _concatenate_architectures_in_one_string(architectures: List[CpuArch]):
    return "_".join(a.value for a in architectures)