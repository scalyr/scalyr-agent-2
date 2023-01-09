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
cp -a "${BUILD_PYTHON}/python/." "${PACKAGE_ROOT}"


function get_standatd_c_binding_path() {
  files=( "${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"/lib-dynload/$1 )
  echo "${files[0]}"
}

function find_dependency_in_elf() {
    elf_path="$1"
    dependency_to_find="$2"
    readelf --dynamic "${elf_path}" | grep NEEDED | grep "${dependency_to_find}" | tr -s ' ' | cut -d ' ' -f6 | tr -d '[' | tr -d ']'
}

function replace_elf_dependency() {
  local elf_path="$1"
  local dependency_to_replace="$2"
  local new_dependency="$3"

  patchelf --replace-needed \
    "${dependency_to_replace}" \
    "${new_dependency}" \
    "${elf_path}"
}

SSL_C_BINDING_PATH="$(get_standatd_c_binding_path _ssl.cpython-*-*-*-*.so)"
function replace_ssh_module_dependencies() {
    elf_path="$1"

    libssl_dependency_name="$(find_dependency_in_elf "${elf_path}" "libssl.so")"
    libcrypto_dependency_name="$(find_dependency_in_elf "${elf_path}" "libcrypto.so")"
}





exit 0
SSL_C_BINDING_LIBSLL_DEPENDENCY_NAME="$(find_dependency_in_elf "${SSL_C_BINDING_PATH}" "libssl.so")"
SSL_C_BINDING_LIBCRYPTO_DEPENDENCY_NAME="$(find_dependency_in_elf "${SSL_C_BINDING_PATH}" "libcrypto.so")"

REPLACED_LIBSSH_DEPENDENCY_PATH="${INSTALL_PREFIX}/lib/libssl.so"
REPLACED_LIBCRYPTO_DEPENDENCY_PATH="${INSTALL_PREFIX}/lib/libcrypto.so"

replace_elf_dependency "${SSL_C_BINDING_PATH}" "${SSL_C_BINDING_LIBSLL_DEPENDENCY_NAME}" "${REPLACED_LIBSSH_DEPENDENCY_PATH}"
replace_elf_dependency "${SSL_C_BINDING_PATH}" "${SSL_C_BINDING_LIBCRYPTO_DEPENDENCY_NAME}" "${REPLACED_LIBCRYPTO_DEPENDENCY_PATH}"


HASHLIB_C_BINDING_PATH="$(get_standatd_c_binding_path _hashlib.cpython-*-*-*-*.so)"

HASHLIB_C_BINDING_LIBCRYPTO_DEPENDENCY_NAME="$(find_dependency_in_elf "${HASHLIB_C_BINDING_PATH}" "libcrypto.so")"

replace_elf_dependency "${HASHLIB_C_BINDING_PATH}" "${HASHLIB_C_BINDING_LIBCRYPTO_DEPENDENCY_NAME}" "${REPLACED_LIBCRYPTO_DEPENDENCY_PATH}"

mkdir -p "${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/openssl"
cp -a \
  "${BUILD_OPENSSL}/openssl${LIBSSL_DIR}"/libssl.so* \
  "${BUILD_OPENSSL}/openssl${LIBSSL_DIR}"/libcrypto.so* \
  "${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/openssl"

ln -s "openssl/libssl.so" "${PACKAGE_ROOT}${REPLACED_LIBSSH_DEPENDENCY_PATH}"
ln -s "openssl/libcrypto.so" "${PACKAGE_ROOT}${REPLACED_LIBCRYPTO_DEPENDENCY_PATH}"








# Remove some of the files to reduce package size
PYTHON_EXEC_LIBS_PATH="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"
PYTHON_LIBS_PATH="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"

find "${PYTHON_EXEC_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;
find "${PYTHON_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;

rm -r "${PYTHON_LIBS_PATH}/test"
rm -r "${PYTHON_LIBS_PATH}"/config-"${PYTHON_SHORT_VERSION}"-*-linux-gnu/
rm -r "${PYTHON_LIBS_PATH}/lib2to3"
