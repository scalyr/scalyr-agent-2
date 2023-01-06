#!/usr/bin/env bash
# Copyright 2014-2022 Scalyr Inc.
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

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script builds Python interpreter from source and then also modifies the result filesystem structure. In short:
#   all installation files of the built Python interpreter have to be located in its special sub-directory.
#   This is crucial, because we have to make sure that Python dependency package won't affect any existing Python
#   installations. For example, instead of filesystem hierarchy of a "normal" package:
#       /usr
#          bin/<package_files>
#          lib/<package_files>
#          share/<package_files>
#          include/<package_files>
#       <etc?
#   the result package is expected to be:
#       /usr
#          lib/<subdir>/<exec-prefix>       // Prefix directory with all platform-dependent files.
#          share/<subdir>/<prefix>          // Prefix directory with all platform-independent files.
#
#
# It expects next environment variables:
#
#   PYTHON_VERSION: Version of the Python to build.
#   PYTHON_INSTALL_PREFIX: Install prefix for the Python installation.
#   SUBDIR_NAME: Name of the sub-directory.

set -e

# shellcheck disable=SC1090
source ~/.bashrc

PACKAGE_ROOT="${STEP_OUTPUT_PATH}/root"
mkdir -p "${PACKAGE_ROOT}"
cp -a "${BUILD_PYTHON}/." "${PACKAGE_ROOT}"

## Copy Python dependency shared libraries.
#cp -a /usr/local/lib/libz.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libbz2.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libedit.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libncurses.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/liblzma.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libuuid.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libgdbm.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib/libgdbm_compat.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a /usr/local/lib64/libffi.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a "${LIBSSL_DIR}"/libcrypto.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
#cp -a "${LIBSSL_DIR}"/libssl.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"

## Copy wrapper for Python interpreter executable.
#cp -a "${SOURCE_ROOT}/agent_build_refactored/managed_packages/files/python3" "${PACKAGE_ROOT}${INSTALL_PREFIX}/bin/python3"

# Remove some of the files to reduce package size
PYTHON_EXEC_LIBS_PATH="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"
PYTHON_LIBS_PATH="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"

find "${PYTHON_EXEC_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;
find "${PYTHON_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;

rm -r "${PYTHON_LIBS_PATH}/test"
rm -r "${PYTHON_LIBS_PATH}"/config-"${PYTHON_SHORT_VERSION}"-*-linux-gnu/
rm -r "${PYTHON_LIBS_PATH}/lib2to3"
