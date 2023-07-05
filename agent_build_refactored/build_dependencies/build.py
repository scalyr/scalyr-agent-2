import dataclasses
import enum
import pathlib
import re
import sys

if __name__ == '__main__':
    sys.path.append(str(pathlib.Path(__file__).parent.parent.parent))

from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.managed_packages.build_dependencies_versions import RUST_VERSION

from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep
from agent_build_refactored.build_dependencies.build_agent_libs_venv import BuildAgentLibsVenvStep
from agent_build_refactored.build_dependencies.python.build_python_for_packages import BuildPythonForPackagesStep

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


# build_python_step = BuilderPythonStep(
#     python_version="3.11.2",
#     #openssl_type="switchable",
#     openssl_version="3.0.7",
#     #architecture=CpuArch.ARMV7,
#     architecture=CpuArch.x86_64,
#     libc="musl",
# )


# build_dev_requirements_step = BuildDevRequirementsStep(
#     build_python_step=build_python_step,
# )
#
# prepare_build_base_with_python_step = PrepareBuildBaseWithPythonStep(
#     build_dev_requirements_step=build_dev_requirements_step
# )
#
# build_agent_libs_venv = BuildAgentLibsVenvStep(
#     prepare_build_base_with_python_step=prepare_build_base_with_python_step
# )

build_python_with_switchable_openssl = BuildPythonForPackagesStep(
    python_version="3.11.2",
    openssl_1_version="1.1.1s",
    openssl_3_version="3.0.7",
    architecture=CpuArch.x86_64,
    libc="musl",
)


#build_python_step.run_and_output_in_loacl_directory()

#build_dev_requirements_step.run_and_output_in_loacl_directory()

#prepare_build_base_with_python_step.run_and_output_in_oci_tarball()
#prepare_build_base_with_python_step.run_and_output_in_docker()


#prepare_build_base_with_python_step.run_and_output_in_docker()


#build_agent_libs_venv.run_and_output_in_loacl_directory()


if __name__ == '__main__':
    sys.path.append(str(pathlib.Path(__file__).parent.parent.parent))
    build_python_with_switchable_openssl.run_and_output_in_local_directory(use_only_cache=False)


a=10
