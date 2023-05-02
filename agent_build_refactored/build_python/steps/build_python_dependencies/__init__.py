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

from agent_build_refactored.tools.runner import RunnerStep, EnvironmentRunnerStep


def create_step(
        name_suffix: str,
        install_build_environment_step: EnvironmentRunnerStep,
        download_build_dependencies_step: RunnerStep,
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
        run_in_remote_docker: bool = False

) -> RunnerStep:

    """
    Create step that build all dependencies for the Python interpreter.
    :param name_suffix: Suffix fot the step name
    :param install_build_environment_step: Step that acts like a base for the result step.
    :param download_build_dependencies_step: Step that downloads source code for python interpreter and its
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
    :param run_in_remote_docker: Run in remote docker engine, if needed.
    """
    return RunnerStep(
        name=f"build_python_dependencies_{name_suffix}",
        script_path=pl.Path(__file__).parent / "build_python_dependencies.sh",
        base=install_build_environment_step,
        dependency_steps={
            "DOWNLOAD_BUILD_DEPENDENCIES": download_build_dependencies_step
        },
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
        },
        run_in_remote_docker_if_available=run_in_remote_docker,
    )