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

import enum
import re
import pathlib as pl

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()

AGENT_VERSION = (SOURCE_ROOT / "VERSION").read_text().strip()

AGENT_BUILD_OUTPUT_PATH = SOURCE_ROOT / "agent_build_output"
OCI_LAYOUTS_DIR = AGENT_BUILD_OUTPUT_PATH / "oci_layouts"


class CpuArch(enum.Enum):
    x86_64 = "x86_64"
    AARCH64 = "aarch64"
    ARMV7 = "armv7"

    def as_docker_platform(self):
        if self.value == "x86_64":
            return "linux/amd64"

        if self.value == "aarch64":
            return "linux/arm64"

        if self.value == "armv7":
            return "linux/arm/v7"


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

REQUIREMENTS_AGENT_COMMON = _REQUIREMENT_FILE_COMPONENTS["COMMON"]
REQUIREMENTS_AGENT_COMMON_PLATFORM_DEPENDENT = _REQUIREMENT_FILE_COMPONENTS[
    "COMMON_PLATFORM_DEPENDENT"
]

AGENT_REQUIREMENTS = f"{REQUIREMENTS_AGENT_COMMON}\n" \
                     f"{REQUIREMENTS_AGENT_COMMON_PLATFORM_DEPENDENT}"


REQUIREMENTS_DEV_COVERAGE = _REQUIREMENT_FILE_COMPONENTS["DEV_COVERAGE"]
