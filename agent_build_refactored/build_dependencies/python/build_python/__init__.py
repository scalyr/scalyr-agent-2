import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep
from agent_build_refactored.build_dependencies.python.download_source_base import DownloadSourcesBaseStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies import (
    BuildXZStep,
    BuildPythonOpenSSLStep,
    BuildPythonSqliteStep,
    BuildPythonZlibStep,
    BuildPythonBzipStep,
    BuildPythonUtilLinuxStep,
    BuildPythonNcursesStep,
    BuildPythonLibeditStep,
    BuildPythonLibffiStep,
)
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import (
    COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
)
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies import BuildPytonDependenciesStep

_PARENT_DIR = pl.Path(__file__).parent


class BuilderPythonStep(BuilderStep):

    def __init__(
        self,
        download_sources_step: DownloadSourcesStep,
        prepare_build_base_step: PrepareBuildBaseStep,
        openssl_version: str,
        install_prefix: pl.Path,
        dependencies_install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC,
    ):
        self.download_sources_step = download_sources_step
        self.architecture = architecture
        self.libc = libc
        self.openssl_version = openssl_version
        self.install_prefix = install_prefix
        self.dependencies_install_prefix = dependencies_install_prefix
        self.prepare_build_base_step = prepare_build_base_step

        # self.build_xz_step = BuildXZStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_sqlite_step = BuildPythonSqliteStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_zlib_step = BuildPythonZlibStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_bzip_step = BuildPythonBzipStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_util_linux_step = BuildPythonUtilLinuxStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_ncurses_step = BuildPythonNcursesStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # self.build_libedit_step = BuildPythonLibeditStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        #     build_ncurses_step=self.build_ncurses_step,
        # )
        #
        # self.build_libffi_step = BuildPythonLibffiStep(
        #     download_source_step=self.download_sources_step,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )
        #
        # openssl_major_version = openssl_version.strip(".")[0]
        #
        # self.build_openssl_step = BuildPythonOpenSSLStep(
        #     download_source_step=self.download_sources_step,
        #     major_version=openssl_major_version,
        #     install_prefix=dependencies_install_prefix,
        #     architecture=self.architecture,
        #     libc=self.libc,
        # )

        self.build_python_dependencies = BuildPytonDependenciesStep(
            download_sources_step=self.download_sources_step,
            prepare_build_base=self.prepare_build_base_step,
            install_prefix=dependencies_install_prefix,
            architecture=architecture,
            libc=libc,
        )

        openssl_major_version = openssl_version.strip(".")[0]

        super(BuilderPythonStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            build_contexts=[
                self.prepare_build_base_step,
                self.download_sources_step,
                self.build_python_dependencies,
                # self.build_xz_step,
                # self.build_sqlite_step,
                # self.build_zlib_step,
                # self.build_bzip_step,
                # self.build_util_linux_step,
                # self.build_ncurses_step,
                # self.build_libedit_step,
                # self.build_libffi_step,
                # self.build_openssl_step,
            ],
            build_args={
                "INSTALL_PREFIX": str(self.install_prefix),
                "OPENSSL_MAJOR_VERSION": openssl_major_version,
                "COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX": COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
                "ARCH": architecture.value,
                "LIBC": libc,
            },
            platform=architecture,
            unique_name_suffix=f"_with_openssl_{openssl_major_version}"
        )