import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep

_PARENT_DIR = pl.Path(__file__).parent


class DownloadSourcesStep(BuilderStep):
    def __init__(
            self,
            python_version: str,
            bzip_version: str,
            libedit_version_commit: str,
            libffi_version: str,
            ncurses_version: str,
            openssl_1_version: str,
            openssl_3_version: str,
            tcl_version_commit,
            sqlite_version_commit: str,
            util_linux_version: str,
            xz_version: str,
            zlib_version: str,
    ):
        self.python_version = python_version
        self.bzip_version = bzip_version
        self.libedit_version_commit = libedit_version_commit
        self.libffi_version = libffi_version
        self.ncurses_version = ncurses_version
        self.openssl_1_version = openssl_1_version
        self.openssl_3_version = openssl_3_version
        self.tcl_version_commit = tcl_version_commit
        self.sqlite_version_commit = sqlite_version_commit
        self.util_linux_version = util_linux_version
        self.xz_version = xz_version
        self.zlib_version = zlib_version

        super(DownloadSourcesStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            build_args={
                "PYTHON_VERSION": python_version,
                "BZIP_VERSION": bzip_version,
                "LIBEDIT_VERSION_COMMIT": libedit_version_commit,
                "LIBFFI_VERSION": libffi_version,
                "NCURSES_VERSION": ncurses_version,
                "OPENSSL_1_VERSION": openssl_1_version,
                "OPENSSL_3_VERSION": openssl_3_version,
                "TCL_VERSION_COMMIT": tcl_version_commit,
                "SQLITE_VERSION_COMMIT": sqlite_version_commit,
                "UTIL_LINUX_VERSION": util_linux_version,
                "XZ_VERSION": xz_version,
                "ZLIB_VERSION": zlib_version,
            },
            platform=CpuArch.x86_64,
        )