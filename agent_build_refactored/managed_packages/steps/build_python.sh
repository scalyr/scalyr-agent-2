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
#          libexec/<subdir>/<package_files>       // The bin folder files are moved to libexec
#                                                 // because its files are not supposed to be used by user, only by
#                                                 // other packages.
#          lib/<subdir>/<package_files>
#          share/<subdir>/<package_files>
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

mkdir /tmp/build-python
pushd /tmp/build-python
curl -L "https://github.com/python/cpython/archive/refs/tags/v${PYTHON_VERSION}.tar.gz" > python.tar.gz
tar -xvf python.tar.gz
pushd "cpython-${PYTHON_VERSION}"
mkdir build
pushd build

BIN_DIR="libexec"
LIB_DIR="lib"
DATA_ROOT_DIR="share"
INCLUDE_DIR="include"

PACKAGE_INSTALL_PREFIX="/usr/share/${SUBDIR_NAME}"
PACKAGE_INSTALL_EXEC_PREFIX="/usr/lib/${SUBDIR_NAME}"

# Configure Python. Also provide options to store result files in sub-directories.
../configure \
  CFLAGS="-I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:${LD_LIBRARY_PATH}" \
	--enable-shared \
	--with-openssl="/usr/local" \
	--with-readline=edit \
	--prefix="${PACKAGE_INSTALL_PREFIX}" \
	--exec-prefix="${PACKAGE_INSTALL_EXEC_PREFIX}" \
	--with-ensurepip=upgrade \
	--with-suffix="-orig"

#		--enable-optimizations \
#	--with-lto \


BUILD_ROOT="/tmp/python"

make -j "$(nproc)"
#make test
make DESTDIR="${BUILD_ROOT}" install
popd
popd
popd

#Uncomment this in order to save built Python files with original filesystem structure. May be useful for debugging.
cp -a ${BUILD_ROOT} "${STEP_OUTPUT_PATH}/python_original"

# Copy Python dependency shared libraries.
cp -a /usr/local/lib/libz.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libbz2.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libedit.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libncurses.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/liblzma.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libuuid.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libgdbm.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib/libgdbm_compat.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib64/libffi.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib64/libcrypto.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"
cp -a /usr/local/lib64/libssl.so* "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib"

# Copy wrapper for Python interpreter executable.
cp -a "${SOURCE_ROOT}/agent_build_refactored/managed_packages/files/python3" "${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/bin/python3"

# Remove some of the files to reduce package size
PYTHON_EXEC_LIBS_PATH="${BUILD_ROOT}${PACKAGE_INSTALL_EXEC_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"
PYTHON_LIBS_PATH="${BUILD_ROOT}${PACKAGE_INSTALL_PREFIX}/lib/python${PYTHON_SHORT_VERSION}"

find "${PYTHON_EXEC_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;
find "${PYTHON_LIBS_PATH}" -name "__pycache__" -type d -prune -exec rm -r {} \;

rm -r "${PYTHON_LIBS_PATH}/test"
rm -r "${PYTHON_LIBS_PATH}/config-${PYTHON_SHORT_VERSION}-x86_64-linux-gnu"
rm -r "${PYTHON_LIBS_PATH}/lib2to3"


cp -a "${BUILD_ROOT}" "${STEP_OUTPUT_PATH}/python"
