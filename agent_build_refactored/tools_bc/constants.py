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
import dataclasses
import enum
import os
import re
import pathlib as pl

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()

AGENT_VERSION = (SOURCE_ROOT / "VERSION").read_text().strip()

AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"

IN_CICD = bool(os.environ.get("AGENT_BUILD_IN_CICD"))


@dataclasses.dataclass(frozen=True)
class DockerPlatformInfo:
    """Dataclass with information about docker platform, e.g. linux/amd64, linux/arm/v7, etc."""

    os: str
    architecture: str
    variant: str = None

    def __str__(self):
        result = f"{self.os}/{self.architecture}"
        if self.variant:
            result = f"{result}/{self.variant}"
        return result

    @property
    def to_dashed_str(self):
        """Replaces slash to dash in platform's canonical format."""
        result = f"{self.os}-{self.architecture}"
        if self.variant:
            result = f"{result}-{self.variant}"
        return result

    @property
    def as_architecture(self):
        name = str(self)
        if "amd64" in name:
            return Architecture.X86_64

        if "arm64" in name or "arm/v8" in name:
            return Architecture.ARM64

        if "arm/v7" in name:
            return Architecture.ARMV7

        if "s390x" in name:
            return Architecture.S390X

        if "mips64le" in name:
            return Architecture.MIPS64LE

        if "riscv64" in name:
            return Architecture.RISCV

        if "ppc64le" in name:
            return Architecture.PPC64LE

        return Architecture.UNKNOWN


class DockerPlatform(enum.Enum):
    AMD64 = DockerPlatformInfo("linux", "amd64")
    ARM64 = DockerPlatformInfo("linux", "arm64")
    # # For Raspberry Pi and other lower powered armv7 based ARM platforms
    ARM = DockerPlatformInfo("linux", "arm")
    ARMV7 = DockerPlatformInfo("linux", "arm", "v7")
    ARMV8 = DockerPlatformInfo("linux", "arm", "v8")
    RISCV = DockerPlatformInfo("linux", "riscv64")
    PPC64LE = DockerPlatformInfo("linux", "ppc64le")
    S390X = DockerPlatformInfo("linux", "s390x")
    MIPS64LE = DockerPlatformInfo("linux", "mips64le")


class Architecture(enum.Enum):
    """
    Architecture types.
    """

    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARM = "arm"
    ARMV7 = "armv7"
    ARMV8 = "armv8"
    RISCV = "riscv64"
    PPC64LE = "ppc64le"
    S390X = "s390x"
    MIPS64LE = "mips64le"
    UNKNOWN = "unknown"

    @property
    def as_docker_platform(self) -> DockerPlatform:
        global _ARCHITECTURE_TO_DOCKER_PLATFORM
        return _ARCHITECTURE_TO_DOCKER_PLATFORM[self]

    @property
    def to_docker_build_triplet(self):
        return f"linux-{self.as_docker_platform.value}"

    @property
    def as_deb_package_arch(self):
        mapping = {
            Architecture.X86_64: "amd64",
            Architecture.ARM64: "arm64",
            Architecture.RISCV: "riscv64",
            Architecture.PPC64LE: "ppc64el",
            Architecture.S390X: "s390x",
            Architecture.MIPS64LE: "mips64el",
            Architecture.UNKNOWN: "all",
        }

        return mapping[self]

    @property
    def as_rpm_package_arch(self):
        mapping = {
            Architecture.X86_64: "x86_64",
            Architecture.ARM64: "aarch64",
            Architecture.RISCV: "riscv64",
            Architecture.PPC64LE: "ppc64le",
            Architecture.S390X: "s390x",
            Architecture.MIPS64LE: "mips64el",
            Architecture.UNKNOWN: "noarch",
        }
        return mapping[self]

    def get_package_arch(self, package_type: str):
        if package_type == "deb":
            return self.as_deb_package_arch
        elif package_type == "rpm":
            return self.as_rpm_package_arch
        else:
            raise Exception(f"Unknown package type: {package_type}")


_ARCHITECTURE_TO_DOCKER_PLATFORM = {
    Architecture.X86_64: DockerPlatform.AMD64,
    Architecture.ARM64: DockerPlatform.ARM64,
    Architecture.ARM: DockerPlatform.ARM,
    Architecture.ARMV7: DockerPlatform.ARMV7,
    Architecture.ARMV8: DockerPlatform.ARMV8,
    Architecture.RISCV: DockerPlatform.RISCV,
    Architecture.MIPS64LE: DockerPlatform.MIPS64LE,
    Architecture.PPC64LE: DockerPlatform.PPC64LE,
    Architecture.S390X: DockerPlatform.S390X,
    # Handle unknown architecture value as x86_64
    Architecture.UNKNOWN: DockerPlatform.AMD64,
}


class PackageType(enum.Enum):
    DEB = "deb"
    RPM = "rpm"
    TAR = "tar"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"
    K8S = "k8s"
    MSI = "msi"


def _parse_requirements_file():
    """
    Parse requirements file and get requirments that are grouped by "Components".
    :return:
    """
    requirements_file_path = SOURCE_ROOT / "dev-requirements-new.txt"
    requirements_file_content = requirements_file_path.read_text()

    current_component_name = None

    all_components = dict()

    for line in requirements_file_content.splitlines():
        if line == "":
            continue

        if line.rstrip().startswith("#"):
            m = re.match(r"^# <COMPONENT:([^>]+)>$", line)

            if m:
                current_component_name = m.group(1)
            else:
                continue
        else:
            if current_component_name is None:
                raise Exception(f"Requirement '{line}' is outside of any COMPONENT")

            component = all_components.get(current_component_name)
            if component:
                all_components[current_component_name] = "\n".join([component, line])
            else:
                all_components[current_component_name] = line

    return all_components


_REQUIREMENT_FILE_COMPONENTS = _parse_requirements_file()

REQUIREMENTS_COMMON = _REQUIREMENT_FILE_COMPONENTS["COMMON"]
REQUIREMENTS_COMMON_PLATFORM_DEPENDENT = _REQUIREMENT_FILE_COMPONENTS[
    "COMMON_PLATFORM_DEPENDENT"
]
