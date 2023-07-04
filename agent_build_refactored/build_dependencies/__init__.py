import collections
import dataclasses
import pathlib as pl
from typing import Dict, List

from agent_build_refactored.tools.constants import CpuArch, LibC

from agent_build_refactored.tools.builder import BuilderStep
from .python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep
from .python.build_python_dependencies.build_openssl import BuildPythonOpenSSLStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep
from .python.build_python import BuilderPythonStep
from .versions import PYTHON_VERSION, OPENSSL_1_VERSION, OPENSSL_3_VERSION
from agent_build_refactored.build_dependencies.ubuntu_toolset import LatestUbuntuToolsetStep

#SUPPORTED_ARCHITECTURES: Dict[CpuArch] = []

PYTHON_INSTALL_PREFIX = pl.Path("/opt/scalyr-agent-2/python3")
PYTHON_DEPENDENCIES_INSTALL_PREFIX = pl.Path("/usr/local")

BUILD_OPENSSL_1_STEPS: Dict[LibC, Dict[CpuArch, BuildPythonOpenSSLStep]] = collections.defaultdict(dict)
BUILD_OPENSSL_3_STEPS: Dict[LibC, Dict[CpuArch, BuildPythonOpenSSLStep]] = collections.defaultdict(dict)
BUILD_PYTHON_WITH_OPENSSL_1_STEPS: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)
BUILD_PYTHON_WITH_OPENSSL_3_STEPS: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)
PREPARE_PYTHON_ENVIRONMENT_STEPS: Dict[LibC, Dict[CpuArch, PrepareBuildBaseWithPythonStep]] = collections.defaultdict(dict)


@dataclasses.dataclass
class MaxCompatibilityPythonBuilderToolchain:
    download_sources_step: DownloadSourcesStep
    build_python_with_openssl_1: BuilderPythonStep
    build_python_with_openssl_3: BuilderPythonStep
    python_environment: PrepareBuildBaseWithPythonStep


MAX_COMPATIBILITY_TOOLCHAINS: Dict[LibC, Dict[CpuArch, MaxCompatibilityPythonBuilderToolchain]] = collections.defaultdict(dict)

for libc in [LibC.GNU]:
    download_sources_step = DownloadSourcesStep.create(
        python_version=PYTHON_VERSION,
        bzip_version="1.0.8",
        libedit_version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
        libffi_version="3.4.2",
        ncurses_version="6.3",
        openssl_1_version=OPENSSL_1_VERSION,
        openssl_3_version=OPENSSL_3_VERSION,
        tcl_version_commit="338c6692672696a76b6cb4073820426406c6f3f9",  # tag - "core-8-6-13"
        sqlite_version_commit="e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2"
        util_linux_version="2.38",
        xz_version="5.2.6",
        zlib_version="1.2.13",
        module=__name__,
    )

    for arch in [CpuArch.x86_64, CpuArch.AARCH64]:
        build_python_with_openssl_1 = BuilderPythonStep.create(
            download_sources_step=download_sources_step,
            openssl_version=OPENSSL_1_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            architecture=arch,
            libc=libc,
            module=__name__,
        )
        BUILD_PYTHON_WITH_OPENSSL_1_STEPS[libc][arch] = build_python_with_openssl_1

        build_python_with_openssl_3 = BuilderPythonStep.create(
            download_sources_step=download_sources_step,
            openssl_version=OPENSSL_3_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            architecture=arch,
            libc=libc,
            module=__name__,
        )
        BUILD_PYTHON_WITH_OPENSSL_3_STEPS[libc][arch] = build_python_with_openssl_3

        prepare_python_environment_step = PrepareBuildBaseWithPythonStep.create(
            build_python_step=build_python_with_openssl_3,
            module=__name__,
        )
        PREPARE_PYTHON_ENVIRONMENT_STEPS[libc][arch] = prepare_python_environment_step

        toolchain = MaxCompatibilityPythonBuilderToolchain(
            download_sources_step=download_sources_step,
            build_python_with_openssl_1=build_python_with_openssl_1,
            build_python_with_openssl_3=build_python_with_openssl_3,
            python_environment=prepare_python_environment_step,
        )
        MAX_COMPATIBILITY_TOOLCHAINS[libc][arch] = toolchain


UBUNTU_TOOLSET_STEP = LatestUbuntuToolsetStep.create(
    module=__name__,
)
