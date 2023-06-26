import dataclasses
import enum
import re

from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.managed_packages.build_dependencies_versions import RUST_VERSION

from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep

BUILD_PYTHON_DIR = SOURCE_ROOT / "agent_build_refactored/build_dependencies/build_python"

PYTHON_INSTALL_PREFIX = "/opt/scalyr-agent-2/python3"


def _target_arch_to_docker_platform(arch: str):
    if arch == "x86_64":
        return "linux/amd64",

    if arch == "aarch64":
        return "linux/arm/64"

    if arch == "armv7":
        return "linux/arm/v7"

    raise Exception(f"Unknown target arch: {arch}")


build_python_step = BuilderPythonStep(
    python_version="3.11.2",
    openssl_type="switchable",
    #architecture=CpuArch.ARMV7,
    architecture=CpuArch.x86_64,
    libc="gnu",
)

prepare_build_base_with_python_step = PrepareBuildBaseWithPythonStep(
    build_python_step=build_python_step
)

build_python_step.run_and_output_in_loacl_directory()

#prepare_build_base_with_python_step.run_and_output_in_oci_tarball()
#prepare_build_base_with_python_step.run_and_output_in_docker()



a=10
