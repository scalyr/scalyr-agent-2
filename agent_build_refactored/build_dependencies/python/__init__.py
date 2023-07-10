import collections
import pathlib as pl
from typing import Dict

from agent_build_refactored.tools.constants import CpuArch, LibC

from agent_build_refactored.tools.builder.builder_step import BuilderStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies import BuildPytonDependenciesStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.build_dev_requirements import BuildDevRequirementsStep
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep

PYTHON_VERSION = "3.11.2"

# Versions of OpenSSL libraries to build for Python.
OPENSSL_1_VERSION = "1.1.1s"
OPENSSL_3_VERSION = "3.0.7"

AGENT_SUBDIR_NAME = "scalyr-agent-2"
AGENT_OPT_DIR = pl.Path("/opt") / AGENT_SUBDIR_NAME

PYTHON_INSTALL_PREFIX = pl.Path(f"{AGENT_OPT_DIR}/python3")
PYTHON_DEPENDENCIES_INSTALL_PREFIX = pl.Path("/usr/local")

DOWNLOAD_SOURCES_STEP = DownloadSourcesStep.create(
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
        )

PREPARE_BUILD_BASE_STEPS: Dict[LibC, Dict[CpuArch, PrepareBuildBaseStep]] = collections.defaultdict(dict)
BUILD_PYTHON_DEPENDENCIES_STEPS: Dict[LibC, Dict[CpuArch, BuildPytonDependenciesStep]] = collections.defaultdict(dict)
BUILD_PYTHON_STEPS: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)
BUILD_DEV_REQUIREMENTS_STEPS: Dict[LibC, Dict[CpuArch, BuildDevRequirementsStep]] = collections.defaultdict(dict)
PREPARE_BUILD_BASE_WITH_PYTHON_STEPS: Dict[LibC, Dict[CpuArch, PrepareBuildBaseWithPythonStep]] = collections.defaultdict(dict)
BUILD_PYTHON_STEPS_WITH_OPENSSL_1: Dict[LibC, Dict[CpuArch, BuilderPythonStep]] = collections.defaultdict(dict)


for libc in [LibC.GNU]:
    for arch in [CpuArch.x86_64, CpuArch.AARCH64]:

        prepare_build_base_step = PrepareBuildBaseStep.create(
            architecture=arch,
            libc=libc,
            run_in_remote_builder_if_possible=True,
        )
        PREPARE_BUILD_BASE_STEPS[libc][arch] =  prepare_build_base_step

        build_python_dependencies_step = BuildPytonDependenciesStep.create(
            download_sources_step=DOWNLOAD_SOURCES_STEP,
            prepare_build_base=prepare_build_base_step,
            install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            run_in_remote_builder_if_possible=True,
        )
        BUILD_PYTHON_DEPENDENCIES_STEPS[libc][arch] = build_python_dependencies_step

        build_python_step = BuilderPythonStep.create(
            download_sources_step=DOWNLOAD_SOURCES_STEP,
            prepare_build_base_step=prepare_build_base_step,
            build_python_dependencies_step=build_python_dependencies_step,
            openssl_version=OPENSSL_3_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            run_in_remote_builder_if_possible=True,
        )

        BUILD_PYTHON_STEPS[libc][arch] = build_python_step

        build_dev_requirements_step = BuildDevRequirementsStep.create(
            build_python_step=build_python_step,
            run_in_remote_builder_if_possible=True,
        )
        BUILD_DEV_REQUIREMENTS_STEPS[libc][arch] = build_dev_requirements_step

        prepare_build_base_with_python_step = PrepareBuildBaseWithPythonStep.create(
            build_python_step=build_python_step,
            build_dev_requirements_step=build_dev_requirements_step,
            run_in_remote_builder_if_possible=True,
        )
        PREPARE_BUILD_BASE_WITH_PYTHON_STEPS[libc][arch] = prepare_build_base_with_python_step

        build_python_step_with_openssl_1 = BuilderPythonStep.create(
            download_sources_step=DOWNLOAD_SOURCES_STEP,
            prepare_build_base_step=prepare_build_base_step,
            build_python_dependencies_step=build_python_dependencies_step,
            openssl_version=OPENSSL_1_VERSION,
            install_prefix=PYTHON_INSTALL_PREFIX,
            dependencies_install_prefix=PYTHON_DEPENDENCIES_INSTALL_PREFIX,
            run_in_remote_builder_if_possible=True,
        )
        BUILD_PYTHON_STEPS_WITH_OPENSSL_1[libc][arch] = build_python_step_with_openssl_1
