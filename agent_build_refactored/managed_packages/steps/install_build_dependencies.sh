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
#   ZX_VERSION: version of XZ Utils to build. Python requirement. ALso required by some make and configure scripts.
#   PERL_VERSION: version of Perl to build. Required by some make and configure scripts.
#   TEXTINFO_VERSION: version of texinfo to build. Required by some make and configure scripts.
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
curl -L "https://tukaani.org/xz/xz-${ZX_VERSION}.tar.gz" > xz.tar.gz
tar -xvf "xz.tar.gz"
pushd "xz-${ZX_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd

mkdir /tmp/build-perl
pushd /tmp/build-perl
curl -L http://www.cpan.org/src/5.0/perl-${PERL_VERSION}.tar.gz > perl.tar.gz
tar -xvf perl.tar.gz
pushd "perl-${PERL_VERSION}"
./Configure -des
make -j "$(nproc)"
make install
popd
popd

mkdir /tmp/build-texinfo
pushd /tmp/build-texinfo
curl -L "https://ftp.gnu.org/gnu/texinfo/texinfo-${TEXTINFO_VERSION}.tar.gz" > texinfo.tar.gz
tar -xvf texinfo.tar.gz
pushd "texinfo-${TEXTINFO_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-m4
pushd /tmp/build-m4
curl -L "https://ftp.gnu.org/gnu/m4/m4-${M4_VERSION}.tar.gz" > m4.tar.gz
tar -xvf m4.tar.gz
pushd "m4-${M4_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-autoconf
pushd /tmp/build-autoconf
curl -L "http://ftp.gnu.org/gnu/autoconf/autoconf-${AUTOCONF_VERSION}.tar.gz" > autoconf.tar.gz
tar -xvf autoconf.tar.gz
pushd "autoconf-${AUTOCONF_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libtool
pushd /tmp/build-libtool
curl -L https://ftpmirror.gnu.org/libtool/libtool-${LIBTOOL_VERSION}.tar.gz > libtool.tar.gz
tar -xvf libtool.tar.gz
pushd "libtool-${LIBTOOL_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-help2man
pushd /tmp/build-help2man
curl -L "https://ftp.gnu.org/gnu/help2man/help2man-${HELP2MAN_VERSION}.tar.xz" > help2man.tar.xz
tar -xvf help2man.tar.xz
pushd "help2man-${HELP2MAN_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-automake
pushd /tmp/build-automake
curl -L "https://ftp.gnu.org/gnu/automake/automake-${AUTOMAKE_VERSION}.tar.gz" > automake.tar.gz
tar -xvf automake.tar.gz
pushd "automake-${AUTOMAKE_VERSION}"
./configure
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-lzma
pushd /tmp/build-lzma
curl -L "https://tukaani.org/lzma/lzma-${LZMA_VERSION}.tar.gz" > lzma.tar.gz
tar -xvf "lzma.tar.gz"
pushd "lzma-${LZMA_VERSION}"
./configure --prefix=/usr/local
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-zlib
pushd /tmp/build-zlib
curl -L "https://www.zlib.net/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
tar -xvf "zlib.tar.gz"
pushd "zlib-${ZLIB_VERSION}"
./configure --shared
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-bzip
pushd /tmp/build-bzip
curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz" > bzip2.tar.gz
tar -xvf "bzip2.tar.gz"
pushd "bzip2-${BZIP_VERSION}"
make -f Makefile-libbz2_so -j "$(nproc)"
make install
cp -a libbz2.so* /usr/local/lib
popd
popd



build_dir="/tmp/build"
mkdir /tmp/build-util-linux
pushd /tmp/build-util-linux
curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v2.38/util-linux-${UTIL_LINUX_VERSION}.tar.gz" > util-linux.tar.gz
tar -xvf "util-linux.tar.gz"
pushd "util-linux-${UTIL_LINUX_VERSION}"
./configure --disable-all-programs --enable-libuuid --prefix=/usr/local
make -j "$(nproc)"
make install
popd
popd


build_dir="/tmp/build"
mkdir /tmp/build-ncurses
pushd /tmp/build-ncurses
curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
tar -xvf "ncurses.tar.gz"
pushd "ncurses-${NCURSES_VERSION}"
./configure --with-shared --prefix=/usr/local
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libedit
pushd /tmp/build-libedit
curl -L "https://thrysoee.dk/editline/libedit-${LIBEDIT_VERSION}.tar.gz" > libedit.tar.gz
tar -xvf "libedit.tar.gz"
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
curl -L "https://ftp.gnu.org/gnu/gdbm/gdbm-${GDBM_VERSION}.tar.gz" > gdbm.tar.gz
tar -xvf "gdbm.tar.gz"
pushd "gdbm-${GDBM_VERSION}"
./configure --enable-libgdbm-compat
make -j "$(nproc)"
make install
popd
popd


mkdir /tmp/build-libffi
pushd /tmp/build-libffi
curl -L "https://codeload.github.com/libffi/libffi/tar.gz/v${LIBFFI_VERSION}" > libffi.tar.gz
tar -xvf libffi.tar.gz
pushd "libffi-${LIBFFI_VERSION}"
./autogen.sh
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
curl -L "https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_${OPENSSL_VERSION_UNDERSCORED}.tar.gz" > openssl.tar.gz
tar -xvf "openssl.tar.gz"
pushd "openssl-OpenSSL_${OPENSSL_VERSION_UNDERSCORED}"
./Configure linux-x86_64 shared
make -j "$(nproc)"
make install_sw
popd


rm -r /tmp/build*