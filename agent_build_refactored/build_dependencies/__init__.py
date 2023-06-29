import collections
import pathlib as pl
from typing import Dict, List

from agent_build_refactored.tools.constants import CpuArch, LibC

from agent_build_refactored.tools.builder import BuilderStep
from .python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep
from .python.build_python_dependencies.build_openssl import BuildPythonOpenSSLStep
from .python.build_python import BuilderPythonStep
from .versions import PYTHON_VERSION, OPENSSL_1_VERSION, OPENSSL_3_VERSION

#SUPPORTED_ARCHITECTURES: Dict[CpuArch] = []

PYTHON_INSTALL_PREFIX = pl.Path("/opt/scalyr-agent-2/python3")
PYTHON_DEPENDENCIES_INSTALL_PREFIX = pl.Path("/usr/local")

BUILD_OPENSSL_1_STEPS: Dict[LibC, Dict[CpuArch, BuildPythonOpenSSLStep]] = collections.defaultdict(dict)
BUILD_OPENSSL_3_STEPS: Dict[LibC, Dict[CpuArch, BuildPythonOpenSSLStep]] = collections.defaultdict(dict)
BUILD_PYTHON_WITH_OPENSSL_1_STEPS: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)
BUILD_PYTHON_WITH_OPENSSL_3_STEPS: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)
PREPARE_PYTHON_ENVIRONMENT_STEPS: Dict[LibC, Dict[CpuArch, PrepareBuildBaseWithPythonStep]] = collections.defaultdict(dict)

for libc in [LibC.GNU]:
    for arch in [CpuArch.x86_64, CpuArch.AARCH64]:
        build_python__with_openssl_1 = BuilderPythonStep(
            python_version=PYTHON_VERSION,
            openssl_version=OPENSSL_1_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            architecture=arch,
            libc=libc,
        )
        BUILD_PYTHON_WITH_OPENSSL_1_STEPS[libc][arch] = build_python__with_openssl_1

        build_python__with_openssl_3 = BuilderPythonStep(
            python_version=PYTHON_VERSION,
            openssl_version=OPENSSL_3_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            architecture=arch,
            libc=libc,
        )
        BUILD_PYTHON_WITH_OPENSSL_3_STEPS[libc][arch] = build_python__with_openssl_3

        step = PrepareBuildBaseWithPythonStep(
            build_python_step=build_python__with_openssl_3,
        )
        PREPARE_PYTHON_ENVIRONMENT_STEPS[libc][arch] = step
