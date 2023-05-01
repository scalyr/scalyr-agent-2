# Copyright 2014-2023 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import pathlib as pl

from agent_build_refactored.tools.constants import DockerPlatform
from agent_build_refactored.tools.runner import RunnerStep, DockerImageSpec

PARENT_PATH = pl.Path(__file__).parent.absolute()


def create_step(
    xz_version: str,
    libffi_version: str,
    util_linux_version: str,
    ncurses_version: str,
    libedit_version_commit: str,
    gdbm_version: str,
    zlib_version: str,
    bzip_version: str,
    openssl_1_version: str,
    openssl_3_version: str,
    python_version: str
):
    """
    Create step that downloads source code for python and all its dependencies.
    :param xz_version: version of XZ Utils to build. Python requirement. ALso required by some make and configure scripts.
    :param libffi_version: version of libffi to build. Python requirement. Provides ctypes module and essential for C bindings.
    :param util_linux_version: version of util linux to build. Python requirement. Provides uuid module.
    :param ncurses_version: version of ncurses to build. Python requirement. Provides curses module.
    :param libedit_version_commit:  version of libedit to build. Python requirement. Provides non-GPL alternative for readline module.
    :param gdbm_version: version of gdbm to build. Python requirement. Provides dbm module.
    :param zlib_version: version of zlib to build. Python requirement. Provides zlib module.
    :param bzip_version: version of bzip to build. Python requirement. Provides bz2 module.
    :param openssl_1_version: Version of OpenSSL 1 to build
    :param openssl_3_version: Version of OpenSSL 3 to build
    :param python_version: Version of Python to download.
    """
    # Step that downloads all Python dependencies.
    return RunnerStep(
        name="download_build_dependencies",
        script_path=PARENT_PATH / "download_build_dependencies.sh",
        tracked_files_globs=[
            PARENT_PATH / "gnu-keyring.gpg",
            PARENT_PATH / "gpgkey-5C1D1AA44BE649DE760A.gpg",
        ],
        base=DockerImageSpec(name="ubuntu:22.04", platform=DockerPlatform.AMD64.value),
        environment_variables={
            "XZ_VERSION": xz_version,
            "LIBFFI_VERSION": libffi_version,
            "UTIL_LINUX_VERSION": util_linux_version,
            "NCURSES_VERSION": ncurses_version,
            "LIBEDIT_VERSION_COMMIT": libedit_version_commit,
            "GDBM_VERSION": gdbm_version,
            "ZLIB_VERSION": zlib_version,
            "BZIP_VERSION": bzip_version,
            "OPENSSL_1_VERSION": openssl_1_version,
            "OPENSSL_3_VERSION": openssl_3_version,
            "PYTHON_VERSION": python_version
        },
    )