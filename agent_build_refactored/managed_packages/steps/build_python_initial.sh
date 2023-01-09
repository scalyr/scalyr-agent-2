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

tar -xzvf "${BUILD_PYTHON_DEPENDENCIES}/common.tar.gz" -C /
cp -a "${BUILD_OPENSSL}/openssl/." /


mkdir /tmp/build-python
pushd /tmp/build-python
curl -L "https://github.com/python/cpython/archive/refs/tags/v${PYTHON_VERSION}.tar.gz" > python.tar.gz
tar -xvf python.tar.gz
pushd "cpython-${PYTHON_VERSION}"
mkdir build
pushd build

# Configure Python. Also provide options to store result files in sub-directories.
../configure \
  CFLAGS="-I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64" \
	--enable-shared \
	--with-openssl="/usr/local" \
	--with-readline=edit \
	--prefix="${INSTALL_PREFIX}" \
	--exec-prefix="${INSTALL_PREFIX}" \
	--with-ensurepip=upgrade \

#cp "config.log" "${STEP_OUTPUT_PATH}"
#exit 0

#		--enable-optimizations \
#	--with-lto \

make -j "$(nproc)"
#make test
make DESTDIR="${STEP_OUTPUT_PATH}" install

popd
popd
popd

