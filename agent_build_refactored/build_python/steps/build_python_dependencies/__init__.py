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