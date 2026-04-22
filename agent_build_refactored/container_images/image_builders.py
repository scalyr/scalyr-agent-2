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

from agent_build_refactored.utils.constants import (
    SOURCE_ROOT,
    CpuArch,
    AGENT_REQUIREMENTS,
    REQUIREMENTS_DEV_COVERAGE,
)

from agent_build_refactored.utils.builder import Builder
from agent_build_refactored.utils.docker.buildx.build import (
    OCITarballBuildOutput,
    BuildOutput, LocalDirectoryBuildOutput
)

from agent_build_refactored.prepare_agent_filesystem import (
    build_linux_fhs_agent_files,
    add_config,
)

_SUPPORTED_ARCHITECTURES = [
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
    ImageType.DOCKER_API: ["scalyr-agent-docker-api"],
}


class ContainerisedAgentBuilder(Builder):
    """
    Class that builds agent container images.
    """

    BASE_DISTRO: str
    TAG_SUFFIXES: List[str]
    AGENT_REQUIREMENTS_EXCLUDE = []

    def __init__(self, base_image_dockerfile, buildx_builder_name=None):
        super(ContainerisedAgentBuilder, self).__init__()

        self._already_build_requirements: Set[CpuArch] = set()
        self.__base_image_dockerfile = base_image_dockerfile
        self.__buildx_builder_name = buildx_builder_name

    @property
    def _common_cache_name(self):
        return f"agent_image_build_{self.__class__.BASE_DISTRO}"

    def __agent_requirements(self):
        return "\n".join(
            [
                dependency
                for dependency in AGENT_REQUIREMENTS.split("\n")
                if not any(
                    dependency.startswith(excluded)
                    for excluded in self.__class__.AGENT_REQUIREMENTS_EXCLUDE
                )
            ]
        )

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
                    final_name = (
                        f"{registry}/{name_prefix}/{image_name}:{tag}{tag_suffix}"
                    )
                    result_names.append(final_name)

        return result_names

    def create_agent_filesystem(self, image_type: ImageType):
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

        agent_package_dir = (
            agent_filesystem_dir / "usr/share/scalyr-agent-2/py/scalyr_agent"
        )

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
        new_agent_main_content = agent_main_content.replace(
            "#!/usr/bin/env python", "#!/usr/bin/env python3", 1
        )
        agent_main_path.write_text(new_agent_main_content)
        return agent_filesystem_dir

    def _build(self,
        image_type: ImageType,
        output: BuildOutput,
        architectures: List[CpuArch] = None,
    ):
        architectures = architectures or self.get_supported_architectures()

        agent_filesystem_dir = self.create_agent_filesystem(image_type=image_type)
        requirements_dir = self.create_requirements_specifications()

        self._buildx_bake(
            bake_file=_PARENT_DIR / "docker-bake.hcl",
            target=f"container-images-{image_type.value}",
            build_vars = {
                "AGENT_FILESYSTEM_DIR": str(agent_filesystem_dir),
                "REQUIREMENTS_DIR": str(requirements_dir),
            },
            architectures = architectures,
            output=output,
            dockerfile_overrides= {
                "runtime-base": self.__base_image_dockerfile,
                "dependencies-builder-base": self.__base_image_dockerfile,
            })

    def create_requirements_specifications(self):
        """Generates the two requirement files needed for the requirements context. The
        regular `requirements.txt` which contains the Python requirements to run the
        Scalyr Agent package. The `test_requirements.txt` which contains additional
        requirements for running the tests package.

        :return: The directory containing the requirements files.
        """
        requirements_specifications_dir = self.work_dir / "requirements_specifications"
        requirements_specifications_dir.mkdir()
        with open(requirements_specifications_dir / "requirements.txt", "w") as requirements_file:
            requirements_file.write(self.__agent_requirements())

        with open(requirements_specifications_dir / "test_requirements.txt", "w") as test_requirements_file:
            test_requirements_file.write(REQUIREMENTS_DEV_COVERAGE)

        return requirements_specifications_dir


    def _buildx_bake(self, bake_file: pl.Path, target: str, build_vars: Dict[str, str], architectures: List[CpuArch],
                     output: BuildOutput, dockerfile_overrides: Dict[str, str]):
        build_vars = build_vars or {}
        dockerfile_overrides = dockerfile_overrides or {}

        print(f"Length of architectures: {len(architectures)}")
        print(f"Same architecture: {architectures[0]}")

        cmd_options = [
            f"--file {bake_file}",
            "--progress=plain",
            f"--allow=fs.read={str(self.work_dir)}",
            f"--set \\*.platform={','.join([x.as_docker_platform() for x in architectures])}",
        ]

        for key, value in dockerfile_overrides.items():
            dockerfile = pl.Path(value)
            cmd_options.append(f"--allow=fs.read={str(dockerfile.parent)}")
            cmd_options.append(f"--set \"{key}.dockerfile={str(dockerfile.name)}\"")
            cmd_options.append(f"--set \"{key}.context={str(dockerfile.parent)}\"")

        if self.__buildx_builder_name:
            cmd_options.append(
                f"--builder={self.__buildx_builder_name}",
            )

        if output:
            if isinstance(output, (OCITarballBuildOutput, LocalDirectoryBuildOutput)):
                cmd_options.append(
                    f"--allow=fs.write={str(output.dest.parent)}"
                )      

            cmd_options.append(
                f"--set {target}.output={output.to_docker_output_option()}"
            )

        cmd_vars = []
        for arg_name, arg_value in build_vars.items():
            cmd_vars.append(f"{arg_name}={arg_value}")

        cmd = [ *cmd_vars, "docker", "buildx", "bake", *cmd_options, target]
        print(f"Executing command: {' '.join(cmd)}")
        process = subprocess.Popen(
            " ".join(cmd),
            cwd=bake_file.parent,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout
            text=True,                 # Return strings instead of bytes
            bufsize=1                  # Line buffered
        )

        captured_output = []

        # Read output line by line as it happens
        for line in iter(process.stdout.readline, ""):
            print(line, end="")        # Print to console in real-time
            captured_output.append(line)

        process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"Build failed with return code: {return_code}")


    def build_oci_tarball(
        self,
        image_type: ImageType,
        architectures: List[CpuArch] = None,
        output_dir: pl.Path = None,
    ):
        """
        Build image in the form of the OCI tarball
        """

        architectures = architectures or self.get_supported_architectures()

        if len(architectures) > 1:
            architecture_name = "multiarch"
        else:
            architecture_name = architectures[0].value

        agent_version = (SOURCE_ROOT / "VERSION").read_text().strip()
        result_oci_tarball = (
            self.result_dir / f"scalyr-agent-2-{image_type.value}-{self.__class__.NAME}-{ agent_version }-{architecture_name}.oci"
        )

        self._build(
            image_type=image_type,
            output=OCITarballBuildOutput(
                dest=result_oci_tarball,
                extract=False,
            ),
            architectures=architectures,
        )

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                result_oci_tarball,
                output_dir,
            )

        return result_oci_tarball

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


# TODO: To promote readability, we should probably eliminate the need for these individual
# "Builder" classes. Their main function is to allow for slight tweaks to the build process
# depending on the image base you are working with. For example, with you are using Alpine as
# your base, then you need to tweak the requirements.txt file a little bit. If you are using
# FIPs, you need to tweak the resulting tags you add to the image (appending _fips to all the tags).
#
# I think it would be somewhat cleaner to just push on the use of overriding a base Dockefile.
# For each builder type, you already are required to pass a difference Dockerfile as base.
# Why not just make that the one thing you need to do?
#
# To do this, you would need to:
# - Have the base Dockerfile be responsible for copying the agent requirements file into the
#   dependency base target -- that way it could modify the requirements list before they
#   are installed into the dependencies target.
# - Use a well-known LABEL to store any modification to the image tag (like adding the _fips
#   suffix) that this system respects.
#
# However, that's all too much clean up work for now.

# Create all image builder classes and make them available from this global collection.
CONTAINERISED_AGENT_BUILDERS: Dict[str, Type[ContainerisedAgentBuilder]] = {}

requirement_libs_exclude = {"alpine": ["orjson", "lz4", "zstandard"]}

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
