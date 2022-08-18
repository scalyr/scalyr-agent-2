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
import pathlib as pl

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()
AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"


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


class DockerPlatform(enum.Enum):
    AMD64 = DockerPlatformInfo("linux", "amd64")
    ARM64 = DockerPlatformInfo("linux", "arm64")
    # # For Raspberry Pi and other lower powered armv7 based ARM platforms
    ARM = DockerPlatformInfo("linux", "arm")
    ARMV7 = DockerPlatformInfo("linux", "arm", "v7")
    ARMV8 = DockerPlatformInfo("linux", "arm", "v8")


class Architecture(enum.Enum):
    """
    Architecture types.
    """

    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARM = "arm"
    ARMV7 = "armv7"
    ARMV8 = "armv8"
    UNKNOWN = "unknown"

    @property
    def as_docker_platform(self) -> str:
        global _ARCHITECTURE_TO_DOCKER_PLATFORM
        return _ARCHITECTURE_TO_DOCKER_PLATFORM[self].value

    @property
    def to_docker_build_triplet(self):
        return f"linux-{self.as_docker_platform}"


_ARCHITECTURE_TO_DOCKER_PLATFORM = {
    Architecture.X86_64: DockerPlatform.AMD64,
    Architecture.ARM64: DockerPlatform.ARM64,
    Architecture.ARM: DockerPlatform.ARM,
    Architecture.ARMV7: DockerPlatform.ARMV7,
    Architecture.ARMV8: DockerPlatform.ARMV8,
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
    K8S_WITH_OPENMETRICS = "k8s-with-openmetrics"
    K8S_RESTART_AGENT_ON_MONITOR_DEATH = "k8s-restart-agent-on-monitor-death"
    MSI = "msi"
