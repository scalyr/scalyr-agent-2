import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies.download_sources_base import DownloadSourcesBaseStep
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

BUILD_TYPE_MAX_COMPATIBILITY = "max_compatibility"
BUILD_TYPE_LATEST = "latest"


class BuilderPythonStep(BuilderStep):
    BUILD_CONTEXT = pl.Path(__file__).parent

    def __init__(
        self,
        python_version: str,
        openssl_version: str,
        #openssl_type: str,
        install_prefix: pl.Path,
        build_type: str,
        dependencies_install_prefix: pl.Path,
        architecture: CpuArch,
        libc: str,
    ):

        self.architecture = architecture
        self.libc = libc
        self.install_prefix = install_prefix
        self.prepare_build_base_step = PrepareBuildBaseStep(
            architecture=architecture,
            libc=libc
        )

        self.download_base_step = DownloadSourcesBaseStep()

        # self.build_xz_step = BuildXZStep(
        #     xz_version="5.2.6",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_sqlite_step = BuildPythonSqliteStep(
        #     sqlite_version_commit="e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2"
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_zlib_step = BuildPythonZlibStep(
        #     version="1.2.13",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_bzip_step = BuildPythonBzipStep(
        #     version="1.0.8",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_util_linux_step = BuildPythonUtilLinuxStep(
        #     version="2.38",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_ncurses_step = BuildPythonNcursesStep(
        #     version="6.3",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # self.build_libedit_step = BuildPythonLibeditStep(
        #     version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
        #     architecture=architecture,
        #     libc=libc,
        #     build_ncurses_step=self.build_ncurses_step,
        # )
        #
        # self.build_libffi_step = BuildPythonLibffiStep(
        #     version="3.4.2",
        #     architecture=architecture,
        #     libc=libc,
        # )
        #
        # # self.build_openssl_1_step = BuildPythonOpenSSLStep(
        # #     version="1.1.1s",
        # #     architecture=architecture,
        # #     libc=libc,
        # # )
        #
        # openssl_major_version = openssl_version.strip(".")[0]
        # self.build_openssl_step = BuildPythonOpenSSLStep(
        #     version=openssl_version,
        #     major_version=openssl_major_version,
        #     architecture=architecture,
        #     libc=libc,
        # )

        build_contexts = [
            self.prepare_build_base_step,
            self.download_base_step,
        ]

        openssl_major_version = openssl_version.strip(".")[0]

        if build_type == BUILD_TYPE_MAX_COMPATIBILITY:
            build_python_dependencies_steps = self._init_max_compatibility_dependencies_(
                openssl_version=openssl_version,
                openssl_major_version=openssl_major_version,
                install_prefix=dependencies_install_prefix,
            )
            build_contexts.extend(build_python_dependencies_steps)

        super(BuilderPythonStep, self).__init__(
            name=f"build_python_with_openssl_{openssl_major_version}",
            context=self.__class__.BUILD_CONTEXT,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            build_contexts=build_contexts,
            build_args={
                "PYTHON_VERSION": python_version,
                "PYTHON_BUILD_TYPE": build_type,
                "INSTALL_PREFIX": str(self.install_prefix),
                #"OPENSSL_TYPE": openssl_type,
                "OPENSSL_MAJOR_VERSION": openssl_major_version,
                "COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX": COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
                "ARCH": architecture.value,
                "LIBC": libc,
            },
            platform=architecture,
            cache=False
        )

    def _init_max_compatibility_dependencies_(
            self,
            openssl_version: str,
            openssl_major_version: str,
            install_prefix: pl.Path
    ):
        self.build_xz_step = BuildXZStep(
            version="5.2.6",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_sqlite_step = BuildPythonSqliteStep(
            version_commit="e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2"
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_zlib_step = BuildPythonZlibStep(
            version="1.2.13",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_bzip_step = BuildPythonBzipStep(
            version="1.0.8",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_util_linux_step = BuildPythonUtilLinuxStep(
            version="2.38",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_ncurses_step = BuildPythonNcursesStep(
            version="6.3",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        self.build_libedit_step = BuildPythonLibeditStep(
            version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
            build_ncurses_step=self.build_ncurses_step,
        )

        self.build_libffi_step = BuildPythonLibffiStep(
            version="3.4.2",
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        # self.build_openssl_1_step = BuildPythonOpenSSLStep(
        #     version="1.1.1s",
        #     architecture=architecture,
        #     libc=libc,
        # )

        self.build_openssl_step = BuildPythonOpenSSLStep(
            version=openssl_version,
            major_version=openssl_major_version,
            install_prefix=install_prefix,
            architecture=self.architecture,
            libc=self.libc,
        )

        return [
            self.build_xz_step,
            self.build_sqlite_step,
            self.build_zlib_step,
            self.build_bzip_step,
            self.build_util_linux_step,
            self.build_ncurses_step,
            self.build_libedit_step,
            self.build_libffi_step,
            # self.build_openssl_1_step,
            self.build_openssl_step,
        ]