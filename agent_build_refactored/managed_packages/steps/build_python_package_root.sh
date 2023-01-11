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
  files=( "$dir_path"/$name )
  echo "${files[0]}"
}

OPENSSL_LIBS_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/lib/openssl"
mkdir -p "${OPENSSL_LIBS_DIR}"


# This function copies Python's ssl module related files.
function copy_and_patch_openssl_libs() {
  local openssl_libs_dir="$1"
  local python_step_output_dir="$2"
  local dst_dir="$3"

  local libssl_path="$(find "${openssl_libs_dir}" -name "libssl.so.*")"
  local libcrypto_path="$(find "${openssl_libs_dir}" -name "libcrypto.so.*")"
  local libssl_filename="$(basename "${libssl_path}")"
  local libcrypto_filename="$(basename "${libcrypto_path}")"

  mkdir -p "${dst_dir}"
  # Copy shared objects and other files of the OpenSSL library.
  cp "${libssl_path}" "${dst_dir}"
  cp "${libcrypto_path}" "${dst_dir}"

  local python_step_bindings_dir="${python_step_output_dir}${INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}/lib-dynload"

  # Copy _ssl and _hashlib modules.
  local ssl_binding_path="$(get_standard_c_binding_path "${python_step_bindings_dir}" _ssl.cpython-*-*-*-*.so)"
  local hashlib_binding_path="$(get_standard_c_binding_path "${python_step_bindings_dir}" _hashlib.cpython-*-*-*-*.so)"

  local bindings_dir="${dst_dir}/bindings"

  # Copy original ssl and hashlib C bindings. They will be used in case if appropriate OpenSSL version is
  # found on system.
  local original_bindings_dir="${bindings_dir}/original"
  mkdir -p "${original_bindings_dir}"
  cp "${ssl_binding_path}" "${original_bindings_dir}"
  cp "${hashlib_binding_path}" "${original_bindings_dir}"

  # In case if there is no appropriate system OpenSSL, we also copy the same C bindings, but which are hardcoded
  # to use OpenSSL shared objects that are shipped with the package.
  local patched_bindings_dir="${bindings_dir}/patched"
  mkdir -p "${patched_bindings_dir}"
  local patched_ssl_binding_path="${patched_bindings_dir}/$(basename "${ssl_binding_path}")"
  local patched_hashlib_binding_path="${patched_bindings_dir}/$(basename "${hashlib_binding_path}")"
  cp "${ssl_binding_path}" "${patched_bindings_dir}"
  cp "${hashlib_binding_path}" "${patched_bindings_dir}"

  new_dependencies_dir="$(realpath --relative-to "${PACKAGE_ROOT}" "${dst_dir}")"
  # Patch ssl and hashlib C bindings and hardcode package's shared objects as dependencies.
  patchelf --replace-needed "${libssl_filename}" "/${new_dependencies_dir}/${libssl_filename}" "${patched_ssl_binding_path}"
  patchelf --replace-needed "${libcrypto_filename}" "/${new_dependencies_dir}/${libcrypto_filename}" "${patched_ssl_binding_path}"
  patchelf --replace-needed "${libcrypto_filename}" "/${new_dependencies_dir}/${libcrypto_filename}" "${patched_hashlib_binding_path}"
}

# Copy ssl modules and libraries which are compiled for OpenSSL 1.1.1
copy_and_patch_openssl_libs "${BUILD_OPENSSL_1_1_1}${LIBSSL_DIR}" "${BUILD_PYTHON_WITH_OPENSSL_1_1_1}" "${OPENSSL_LIBS_DIR}/1_1_1"
# Copy ssl modules and libraries which are compiled for OpenSSL 3
copy_and_patch_openssl_libs "${BUILD_OPENSSL_3}${LIBSSL_DIR}" "${BUILD_PYTHON_WITH_OPENSSL_3}" "${OPENSSL_LIBS_DIR}/3"


# Patch Python executable and hardcode libpython.so, so runtime linker does not have to search for it.
patchelf --replace-needed \
  "libpython${PYTHON_SHORT_VERSION}.so.1.0" \
  "${INSTALL_PREFIX}/lib/libpython${PYTHON_SHORT_VERSION}.so.1.0" \
  "${PACKAGE_ROOT}${INSTALL_PREFIX}/bin/python${PYTHON_SHORT_VERSION}"

# Copy package scriptlets
cp -a "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/install-scriptlets" "${STEP_OUTPUT_PATH}/scriptlets"

# Copy executable that allows configure the package.
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_python3/agent-python3-config" "${PACKAGE_ROOT}${INSTALL_PREFIX}/bin"

# Copy package's configuration files.
ETC_DIR="${PACKAGE_ROOT}${INSTALL_PREFIX}/etc"
mkdir -p "${ETC_DIR}"
echo "auto" > "${ETC_DIR}/preferred_openssl"
