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
# This script builds root of the Agent's dependency package with Python interpreter.
#

set -e

# shellcheck disable=SC1090
source ~/.bashrc

PACKAGE_ROOT="${STEP_OUTPUT_PATH}/root"
mkdir -p "${PACKAGE_ROOT}"
cp -a "${BUILD_PYTHON_WITH_OPENSSL_1_1_1}/." "${PACKAGE_ROOT}"

# Remove some of the files to reduce package size
PYTHON_LIBS_PATH="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"

find "${PYTHON_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;

rm -r "${PYTHON_LIBS_PATH}/test"
rm -r "${PYTHON_LIBS_PATH}"/config-"${PYTHON_SHORT_VERSION}"-*-linux-gnu/
rm -r "${PYTHON_LIBS_PATH}/lib2to3"


function get_standard_c_binding_path() {
  dir_path="$1"
  name="$2"
  # shellcheck disable=SC2206
  files=( "$dir_path"/$name )
  echo "${files[0]}"
}

OPENSSL_LIBS_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/openssl"
mkdir -p "${OPENSSL_LIBS_DIR}"


# This function copies Python's ssl module related files.
function copy_openssl_libs() {
  local openssl_libs_dir="$1"
  local python_step_output_dir="$2"
  local dst_dir="$3"

  local libssl_path
  libssl_path="$(find "${openssl_libs_dir}" -name "libssl.so.*")"
  local libcrypto_path
  libcrypto_path="$(find "${openssl_libs_dir}" -name "libcrypto.so.*")"

  local libs_dir="${dst_dir}/libs"
  mkdir -p "${libs_dir}"
  # Copy shared objects and other files of the OpenSSL library.
  cp "${libssl_path}" "${libs_dir}"
  cp "${libcrypto_path}" "${libs_dir}"

  local python_step_bindings_dir="${python_step_output_dir}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}/lib-dynload"

  # Copy _ssl and _hashlib modules.
  local ssl_binding_path
  ssl_binding_path="$(get_standard_c_binding_path "${python_step_bindings_dir}" _ssl.cpython-*-*-*-*.so)"
  local hashlib_binding_path
  hashlib_binding_path="$(get_standard_c_binding_path "${python_step_bindings_dir}" _hashlib.cpython-*-*-*-*.so)"

  local bindings_dir="${dst_dir}/bindings"

  # Copy original ssl and hashlib C bindings. They will be used in case if appropriate OpenSSL version is
  # found on system.
  mkdir -p "${bindings_dir}"
  cp "${ssl_binding_path}" "${bindings_dir}"
  cp "${hashlib_binding_path}" "${bindings_dir}"
}

# Copy ssl modules and libraries which are compiled for OpenSSL 1.1.1
copy_openssl_libs "${BUILD_OPENSSL_1_1_1}${LIBSSL_DIR}" "${BUILD_PYTHON_WITH_OPENSSL_1_1_1}" "${OPENSSL_LIBS_DIR}/1_1_1"
# Copy ssl modules and libraries which are compiled for OpenSSL 3
copy_openssl_libs "${BUILD_OPENSSL_3}${LIBSSL_DIR}" "${BUILD_PYTHON_WITH_OPENSSL_3}" "${OPENSSL_LIBS_DIR}/3"


RESULT_PYTHON_SSL_BINDINGS_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}/lib-dynload"
rm "$(get_standard_c_binding_path "${RESULT_PYTHON_SSL_BINDINGS_DIR}" _ssl.cpython-*-*-*-*.so)"
rm "$(get_standard_c_binding_path "${RESULT_PYTHON_SSL_BINDINGS_DIR}" _hashlib.cpython-*-*-*-*.so)"

# Copy package scriptlets
cp -a "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/install-scriptlets" "${STEP_OUTPUT_PATH}/scriptlets"

BIN_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/bin"
# Copy executables that allows to configure the package.
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/agent-python3-config" "${BIN_DIR}"
cp -r "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/internal" "${BIN_DIR}"

# Rename main Python executable to be 'python3-original' and copy our wrapper script instead of it
mv "${PACKAGE_ROOT}${INSTALL_PREFIX}/bin/python${PYTHON_SHORT_VERSION}" "${PACKAGE_ROOT}${INSTALL_PREFIX}/bin/python3-original"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/python3" "${BIN_DIR}/python${PYTHON_SHORT_VERSION}"

# Remove other executables
rm "${BIN_DIR}"/pip*
rm "${BIN_DIR}"/idle*
rm "${BIN_DIR}"/2to3*
rm "${BIN_DIR}"/pydoc*


# Copy package's configuration files.
ETC_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/etc"
mkdir -p "${ETC_DIR}"
echo "auto" > "${ETC_DIR}/preferred_openssl"
