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
# This script build from source all libraries that are required to build Python. Since we build Python and its
# requirements in a legacy OS (such as Centos 6) to achieve binary compatibility, we also have to build many essential
# build tools because tools from legacy OS's ate too old.
#
# It expects next environment variables:
#
#   XZ_VERSION: version of XZ Utils to build. Python requirement. ALso required by some make and configure scripts.
#   PERL_VERSION: version of Perl to build. Required by some make and configure scripts.
#   TEXINFO_VERSION: version of texinfo to build. Required by some make and configure scripts.
#   M4_VERSION: version of M4 to build. Required by some make and configure scripts.
#   AUTOCONF_VERSION: version of autoconf to build. Required by some make and configure scripts.
#   LIBTOOL_VERSION: version of libtool to build. Required by some make and configure scripts.
#   HELP2MAN_VERSION: version of help2man to build. Required by some make and configure scripts.
#   AUTOMAKE_VERSION: version of automake to build. Required by some make and configure scripts.
#   LZMA_VERSION: version of lzma to build. Python requirement.
#   ZLIB_VERSION: version of zlib to build. Python requirement. Provides zlib module.
#   BZIP_VERSION: version of bzip to build. Python requirement. Provides bz2 module.
#   UTIL_LINUX_VERSION: version of lzma to build. Python requirement. Provides uuid module.
#   NCURSES_VERSION: version of ncurses to build. Python requirement. Provides curses module.
#   LIBEDIT_VERSION: version of libedit to build. Python requirement. Provides non-GPL alternative for readline module.
#   GDBM_VERSION: version of gdbm to build. Python requirement. Provides dbm module.
#   LIBFFI_VERSION: version of libffi to build. Python requirement. Provides ctypes module and essential for C bindings.
#   OPENSSL_VERSION: version of OpenSSL to build. Python requirement. Provides ssl module.



set -e

source ~/.bashrc

# NOTE: The order of installation is important.


mkdir /tmp/build-xz
pushd /tmp/build-xz
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/xz/xz.tar.gz"
pushd "xz-${XZ_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd

mkdir /tmp/build-perl
pushd /tmp/build-perl
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/perl/perl.tar.gz"
pushd "perl-${PERL_VERSION}"
./Configure -des
make -j "$(nproc)"
make install
popd
popd

mkdir /tmp/build-texinfo
pushd /tmp/build-texinfo
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/texinfo/texinfo.tar.gz"
pushd "texinfo-${TEXINFO_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-m4
pushd /tmp/build-m4
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/m4/m4.tar.gz"
pushd "m4-${M4_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-autoconf
pushd /tmp/build-autoconf
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/autoconf/autoconf.tar.gz"
pushd "autoconf-${AUTOCONF_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libtool
pushd /tmp/build-libtool
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/libtool/libtool.tar.gz"
pushd "libtool-${LIBTOOL_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-help2man
pushd /tmp/build-help2man
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/help2man/help2man.tar.xz"
pushd "help2man-${HELP2MAN_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-automake
pushd /tmp/build-automake
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/automake/automake.tar.gz"
pushd "automake-${AUTOMAKE_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-zlib
pushd /tmp/build-zlib
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/zlib/zlib.tar.gz"
pushd "zlib-${ZLIB_VERSION}"
./configure --shared
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-bzip
pushd /tmp/build-bzip
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/bzip2/bzip2.tar.gz"
pushd "bzip2-${BZIP_VERSION}"
make -f Makefile-libbz2_so -j "$(nproc)"
make install
cp -a libbz2.so* /usr/local/lib
popd
popd



mkdir /tmp/build-util-linux
pushd /tmp/build-util-linux
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/util-linux/util-linux.tar"
pushd "util-linux-${UTIL_LINUX_VERSION}"
./configure --disable-all-programs --enable-libuuid --prefix=/usr/local
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-ncurses
pushd /tmp/build-ncurses
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/ncurses/ncurses.tar.gz"
pushd "ncurses-${NCURSES_VERSION}"
./configure --with-shared --prefix=/usr/local
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libedit
pushd /tmp/build-libedit
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/libedit/libedit.tar.gz"
pushd "libedit-${LIBEDIT_VERSION}"
./configure \
  CFLAGS="-I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:${LD_LIBRARY_PATH}"
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-gdbm
pushd /tmp/build-gdbm
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/gdbm/gdbm.tar.gz"
pushd "gdbm-${GDBM_VERSION}"
./configure --enable-libgdbm-compat
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libffi
pushd /tmp/build-libffi
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/libffi/libffi.tar.gz"
pushd "libffi-${LIBFFI_VERSION}"
mkdir build
pushd build
../configure --enable-shared
make -j "$(nproc)"
make install
popd
popd
popd


mkdir /tmp/build-openssl
pushd /tmp/build-openssl
OPENSSL_VERSION_UNDERSCORED="${OPENSSL_VERSION//./_}"
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/openssl/openssl.tar.gz"
pushd "openssl-${OPENSSL_VERSION}"
./Configure linux-x86_64 shared
make -j "$(nproc)"
make install_sw
popd


rm -r /tmp/build*
