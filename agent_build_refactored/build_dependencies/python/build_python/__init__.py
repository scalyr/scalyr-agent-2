import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies.download_sources_base import DownloadSourcesBaseStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies import (
    BuildPythonXZStep,
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



def _get_python_x_y_version(version: str):
    return ".".join(version.split(".")[:2])


class BuilderPythonStep(BuilderStep):
    BUILD_CONTEXT = pl.Path(__file__).parent

    def __init__(
        self,
        python_version: str,
        openssl_type: str,
        architecture: CpuArch,
        libc: str,
    ):
        self.prepare_build_base_step = PrepareBuildBaseStep(
            architecture=architecture,
            libc=libc
        )

        self.download_base_step = DownloadSourcesBaseStep()

        self.build_xz_step = BuildPythonXZStep(
            xz_version="5.2.6",
            architecture=architecture,
            libc=libc,
        )

        self.build_sqlite_step = BuildPythonSqliteStep(
            sqlite_version_commit="e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2"
            architecture=architecture,
            libc=libc,
        )

        self.build_zlib_step = BuildPythonZlibStep(
            version="1.2.13",
            architecture=architecture,
            libc=libc,
        )

        self.build_bzip_step = BuildPythonBzipStep(
            version="1.0.8",
            architecture=architecture,
            libc=libc,
        )

        self.build_util_linux_step = BuildPythonUtilLinuxStep(
            version="2.38",
            architecture=architecture,
            libc=libc,
        )

        self.build_ncurses_step = BuildPythonNcursesStep(
            version="6.3",
            architecture=architecture,
            libc=libc,
        )

        self.build_libedit_step = BuildPythonLibeditStep(
            version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
            architecture=architecture,
            libc=libc,
            build_ncurses_step=self.build_ncurses_step,
        )

        self.build_libffi_step = BuildPythonLibffiStep(
            version="3.4.2",
            architecture=architecture,
            libc=libc,
        )

        openssl_install_prefix = pl.Path("/opt/scalyr-agent-2/openssl")

        self.build_openssl_1_step = BuildPythonOpenSSLStep(
            version="1.1.1s",
            architecture=architecture,
            libc=libc,
            install_prefix=openssl_install_prefix,
        )

        self.build_openssl_3_step = BuildPythonOpenSSLStep(
            version="3.0.7",
            architecture=architecture,
            libc=libc,
            install_prefix=openssl_install_prefix,
        )

        python_x_y_version = _get_python_x_y_version(version=python_version)

        super(BuilderPythonStep, self).__init__(
            name="build_python",
            context=self.__class__.BUILD_CONTEXT,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            build_contexts=[
                self.prepare_build_base_step,
                self.download_base_step,
                self.build_xz_step,
                self.build_sqlite_step,
                self.build_zlib_step,
                self.build_bzip_step,
                self.build_util_linux_step,
                self.build_ncurses_step,
                self.build_libedit_step,
                self.build_libffi_step,
                self.build_openssl_1_step,
                self.build_openssl_3_step,
            ],
            build_args={
                # "XZ_VERSION": "5.2.6",
                # "ZLIB_VERSION": "1.2.13",
                # "BZIP_VERSION": "1.0.8",
                # "UTIL_LINUX_VERSION": "2.38",
                # "NCURSES_VERSION": "6.3",
                # "LIBFFI_VERSION": "3.4.2",
                # "OPENSSL_1_VERSION": "1.1.1s",
                # "OPENSSL_3_VERSION": "3.0.7",
                # "LIBEDIT_VERSION_COMMIT": "0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030",
                # "TCL_VERSION_COMMIT": "338c6692672696a76b6cb4073820426406c6f3f9",  # tag - "core-8-6-13"}",
                # "SQLITE_VERSION_COMMIT": "e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2",
                "PYTHON_VERSION": python_version,
                "PYTHON_X_Y_VERSION": python_x_y_version,
                "INSTALL_PREFIX": "/opt/scalyr-agent-2/python3",
                "OPENSSL_INSTALL_PREFIX": str(openssl_install_prefix),
                "OPENSSL_TYPE": openssl_type,
                "COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX": COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
                "ARCH": architecture.value,
                "LIBC": libc,
            },
            platform=architecture,
        )