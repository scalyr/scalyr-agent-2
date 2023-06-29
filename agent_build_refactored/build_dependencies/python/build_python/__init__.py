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

_PARENT_DIR = pl.Path(__file__).parent


class BuilderPythonStep(BuilderStep):

    def __init__(
        self,
        python_version: str,
        openssl_version: str,
        install_prefix: pl.Path,
        dependencies_install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC,
    ):

        self.architecture = architecture
        self.libc = libc
        self.install_prefix = install_prefix
        self.dependencies_install_prefix = dependencies_install_prefix
        self.prepare_build_base_step = PrepareBuildBaseStep(
            architecture=architecture,
            libc=libc
        )

        self.download_source_base_step = DownloadSourcesBaseStep()

        self.build_xz_step = BuildXZStep(
            version="5.2.6",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_sqlite_step = BuildPythonSqliteStep(
            version_commit="e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2"
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_zlib_step = BuildPythonZlibStep(
            version="1.2.13",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_bzip_step = BuildPythonBzipStep(
            version="1.0.8",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_util_linux_step = BuildPythonUtilLinuxStep(
            version="2.38",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_ncurses_step = BuildPythonNcursesStep(
            version="6.3",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_libedit_step = BuildPythonLibeditStep(
            version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
            build_ncurses_step=self.build_ncurses_step,
        )

        self.build_libffi_step = BuildPythonLibffiStep(
            version="3.4.2",
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        openssl_major_version = openssl_version.strip(".")[0]

        self.build_openssl_step = BuildPythonOpenSSLStep(
            version=openssl_version,
            major_version=openssl_major_version,
            install_prefix=dependencies_install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        super(BuilderPythonStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            build_contexts=[
                self.prepare_build_base_step,
                self.download_source_base_step,
                self.build_xz_step,
                self.build_sqlite_step,
                self.build_zlib_step,
                self.build_bzip_step,
                self.build_util_linux_step,
                self.build_ncurses_step,
                self.build_libedit_step,
                self.build_libffi_step,
                self.build_openssl_step,
            ],
            build_args={
                "PYTHON_VERSION": python_version,
                "INSTALL_PREFIX": str(self.install_prefix),
                "OPENSSL_MAJOR_VERSION": openssl_major_version,
                "COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX": COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
                "ARCH": architecture.value,
                "LIBC": libc,
            },
            platform=architecture,
            unique_name_suffix=f"_with_openssl_{openssl_major_version}"
        )