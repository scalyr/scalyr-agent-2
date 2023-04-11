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
#   DESTDIR_ROOT: Path to the step's output directory.
#
# This script build from source all libraries that are required to build Python.
#
# It expects next environment variables:
#
#   XZ_VERSION: version of XZ Utils to build. Python requirement. ALso required by some make and configure scripts.
#   ZLIB_VERSION: version of zlib to build. Python requirement. Provides zlib module.
#   BZIP_VERSION: version of bzip to build. Python requirement. Provides bz2 module.
#   UTIL_LINUX_VERSION: version of lzma to build. Python requirement. Provides uuid module.
#   NCURSES_VERSION: version of ncurses to build. Python requirement. Provides curses module.
#   LIBEDIT_VERSION: version of libedit to build. Python requirement. Provides non-GPL alternative for readline module.
#   GDBM_VERSION: version of gdbm to build. Python requirement. Provides dbm module.
#   LIBFFI_VERSION: version of libffi to build. Python requirement. Provides ctypes module and essential for C bindings.

set -e

# shellcheck disable=SC1090
source ~/.bashrc


DESTDIR_ROOT=/tmp/root

mkdir /tmp/build-xz
pushd /tmp/build-xz
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/xz/xz.tar.gz"
pushd "xz-${XZ_VERSION}"
./configure CFLAGS="-fPIC" --enable-shared=no --disable-xzdec --disable-lzmadec
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}" install
popd
popd


mkdir /tmp/build-zlib
pushd /tmp/build-zlib
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/zlib/zlib.tar.gz"
pushd "zlib-${ZLIB_VERSION}"
CFLAGS="-fPIC" ./configure  --static
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}" install
popd
popd


mkdir /tmp/build-bzip
pushd /tmp/build-bzip
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/bzip2/bzip2.tar.gz"
pushd "bzip2-${BZIP_VERSION}"
make install  CFLAGS="-fPIC" PREFIX="${DESTDIR_ROOT}/usr/local" -j "$(nproc)"
popd
popd


mkdir /tmp/build-util-linux
pushd /tmp/build-util-linux
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/util-linux/util-linux.tar"
pushd "util-linux-${UTIL_LINUX_VERSION}"
CFLAGS="-fPIC" ./configure --disable-all-programs --prefix=/usr/local --enable-libuuid --enable-shared=no
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}"  install
popd
popd


mkdir /tmp/build-ncurses
pushd /tmp/build-ncurses
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/ncurses/ncurses.tar.gz"
pushd "ncurses-${NCURSES_VERSION}"
CFLAGS="-fPIC" ./configure --prefix=/usr/local
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}" install
make install
popd
popd


mkdir /tmp/build-libedit
pushd /tmp/build-libedit
cp -a "${DOWNLOAD_BUILD_DEPENDENCIES}/libedit" "."
pushd "libedit"
./configure \
  CFLAGS="-fPIC -I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:${LD_LIBRARY_PATH}" \
  --enable-shared=no
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}" install
popd
popd


mkdir /tmp/build-libffi
pushd /tmp/build-libffi
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/libffi/libffi.tar.gz"
pushd "libffi-${LIBFFI_VERSION}"
mkdir build
pushd build
CFLAGS="-fPIC" ../configure --enable-shared=no
make -j "$(nproc)"
make DESTDIR="${DESTDIR_ROOT}" install
popd
popd
popd


tar -czvf "${STEP_OUTPUT_PATH}/common.tar.gz" -C "${DESTDIR_ROOT}" .
