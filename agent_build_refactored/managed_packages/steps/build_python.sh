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



# Configure Python. Also provide options to store result files in sub-directories.
../configure \
  CFLAGS="-I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:${LD_LIBRARY_PATH}" \
	--enable-shared \
	--with-openssl="/usr/local" \
	--with-readline=edit \
	--prefix="${PYTHON_INSTALL_PREFIX}" \
	--with-ensurepip=install \
	--bindir="${PYTHON_INSTALL_PREFIX}/${BIN_DIR}/${SUBDIR_NAME}" \
	--datarootdir="${PYTHON_INSTALL_PREFIX}/${DATA_ROOT_DIR}/${SUBDIR_NAME}" \
	--includedir="${PYTHON_INSTALL_PREFIX}/${INCLUDE_DIR}/${SUBDIR_NAME}" \
	--with-platlibdir="${LIB_DIR}/${SUBDIR_NAME}"

#	--enable-optimizations \
#	--with-lto \



make -j "$(nproc)"
#make test
make DESTDIR="/tmp/python" install
popd
popd
popd

# Uncomment this in order to save built Python files with original filesystem structure. May be useful for debugging.
# cp -a /tmp/python "${STEP_OUTPUT_PATH}/python_original"


BUILD_ROOT="/tmp/python${PYTHON_INSTALL_PREFIX}"

FINAL_PACKAGE_ROOT="${STEP_OUTPUT_PATH}/python${PYTHON_INSTALL_PREFIX}"

# Create package root with a final structure, where all installation files are located in the sub-directories.
# We have to do this because Python's build script's does not fully respect some options and leave some files
# outside of the sub-directories.

mkdir -p "${FINAL_PACKAGE_ROOT}/${BIN_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${LIB_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}"

# Move created subdirectories.
mv "${BUILD_ROOT}/${BIN_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}"
mv "${BUILD_ROOT}/${LIB_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
mv "${BUILD_ROOT}/${DATA_ROOT_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}/${SUBDIR_NAME}"
mv "${BUILD_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}"

# Copy remaining files that have been created outside of sub-directories to those sub-directories.
cp -ar ${BUILD_ROOT}/bin/. "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILD_ROOT}/lib/. "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILD_ROOT}/share/. "${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILD_ROOT}/include/. "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}"

# Cleanup build root.
rm -r ${BUILD_ROOT}/bin
rm -r ${BUILD_ROOT}/libexec
rm -r ${BUILD_ROOT}/lib
rm -r ${BUILD_ROOT}/share
rm -r ${BUILD_ROOT}/include


function die() {
    message=$1
    >&2 echo "${message}"
    exit 1
}

# Check that there's nothing left in the original build root directory.
BUILT_ROOT_CONTENT=$(find "${BUILD_ROOT}" -type f)
test $( echo -n "${BUILT_ROOT_CONTENT}" | wc -l) = 0 || die "Some files are still remaining not copied to a final package folder. Files: ${BUILT_ROOT_CONTENT}"


# Copy Python dependency shared libraries.
cp -a /usr/local/lib/libz.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libbz2.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libedit.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libncurses.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/liblzma.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libuuid.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libgdbm.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libgdbm_compat.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libffi.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libcrypto.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libssl.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"

# Copy wrapper for Python interpreter executable.
cp -a "${SOURCE_ROOT}/agent_build_refactored/managed_packages/files/scalyr-agent-2-python3" "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}/scalyr-agent-2-python3"

# Remove some of the files to reduce package size
PYTHON_LIBS_PATH="${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}/python${PYTHON_SHORT_VERSION}"

find ${PYTHON_LIBS_PATH} -name "__pycache__" -type d -prune -exec rm -r {} \;
rm -r ${PYTHON_LIBS_PATH}/test
rm -r ${PYTHON_LIBS_PATH}/config-${PYTHON_SHORT_VERSION}-x86_64-linux-gnu
rm -r ${PYTHON_LIBS_PATH}/lib2to3


