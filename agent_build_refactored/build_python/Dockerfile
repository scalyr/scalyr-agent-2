ARG TARGET_CPU
ARG TARGET_VENDOR
ARG TARGET_OS
ARG TARGET_LIBC
ARG TARGET_ABI
ARG TARGET="${TARGET_CPU}-${TARGET_VENDOR}-${TARGET_OS}-${TARGET_LIBC}${TARGET_ABI}"
ARG HOST="x86_64-${TARGET_VENDOR}-${TARGET_OS}-${TARGET_LIBC}"
ARG TARGET_ROOT_PATH="/opt/x-tools/${TARGET}"
ARG IMAGE_PLATFORM

ARG DEFAULT_OPENSSL_MAJOR_VERSION="3"
ARG OPENSSL_INSTALL_PREFIX="/opt/scalyr-agent-2/openssl"
ARG PYTHON_INSTALL_PREFIX="/opt/scalyr-agent-2/python3"

ARG TARGET_SYSROOT="${TARGET_ROOT_PATH}/${TARGET}/sysroot"
ARG COMMON_DEPENDENCIES_INSTALL_PREFIX="${TARGET_SYSROOT}/usr"




FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-gnu_x86_64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as  cross_toolchain_x86_64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-gnu_aarch64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as cross_toolchain_aarch64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-gnu_armv7-unknown-linux-gnueabihf:18cbb43ba750d77ee233c83322991499b6a91895 as cross_toolchain_armv7-unknown-linux-gnueabihf

FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-musl_x86_64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as cross_toolchain_x86_64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-musl_aarch64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as cross_toolchain_aarch64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-musl_armv7-unknown-linux-musleabihf:18cbb43ba750d77ee233c83322991499b6a91895 as cross_toolchain_armv7-unknown-linux-musleabihf

FROM cross_toolchain_${TARGET} as cross_toolchain
ARG TARGET_ROOT_PATH
RUN mkdir -p "/tmp/root${TARGET_ROOT_PATH}"
RUN cp -a "${TARGET_ROOT_PATH}/." "/tmp/root${TARGET_ROOT_PATH}"

FROM ubuntu:jammy-20230522 as blank_base_gnu

FROM alpine:3.18.0 as blank_base_musl

FROM blank_base_gnu as build_base_gnu
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt update && apt install -y  \
    curl tar make git gcc automake autoconf pkg-config gnupg2

FROM blank_base_musl as build_base_musl
RUN apk add \
    curl tar make git gcc automake autoconf pkgconfig gnupg bash libstdc++ musl-dev

SHELL ["/usr/bin/env", "bash", "-c"]

FROM build_base_${TARGET_LIBC} as build_base
ARG TARGET
ARG HOST
ARG TARGET_ROOT_PATH
ARG COMMON_DEPENDENCIES_INSTALL_PREFIX
ENV TARGET="${TARGET}"
ENV HOST="${HOST}"
ENV TARGET_SYSROOT="${TARGET_ROOT_PATH}/${TARGET}/sysroot"
ENV PATH="${TARGET_ROOT_PATH}/bin:${PATH}"
ENV COMMON_DEPENDENCIES_INSTALL_PREFIX="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"

COPY --from=cross_toolchain ${TARGET_ROOT_PATH} "${TARGET_ROOT_PATH}"
WORKDIR /tmp/build


FROM build_base as build_tcl_base
WORKDIR build_tcl
RUN git clone "https://github.com/tcltk/tcl.git"
WORKDIR tcl
ARG TCL_VERSION_COMMIT
RUN git checkout "${TCL_VERSION_COMMIT}"
WORKDIR unix
ENV TCL_INSTALL_PREFIX=/usr/local

FROM build_tcl_base as build_tcl_base_native
RUN ./configure --prefix=/usr/local
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install
RUN tar cfz /tmp/root.tar -C /tmp/root .


FROM build_tcl_base as build_tcl_base_cross
RUN ./configure --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install



FROM build_base as build_sqlite
#COPY --from=build_tcl_base_native /tmp/root.tar /tmp/build_tcl_base_native.tar
#RUN tar xfv /tmp/build_tcl_base_native.tar -C /
#COPY --from=build_tcl_base_cross /tmp/root/. /



WORKDIR build_sqlite
RUN git clone "https://github.com/sqlite/sqlite.git"
WORKDIR sqlite
ARG SQLITE_VERSION_COMMIT
RUN git checkout "${SQLITE_VERSION_COMMIT}"
WORKDIR build
RUN apk add tcl
#COPY --from=build_tcl_base_native /tmp/root.tar /tmp/build_tcl_base_native.tar
#RUN tar xfv /tmp/build_tcl_base_native.tar -C /
#COPY --from=build_tcl_base_cross /tmp/root/. /
RUN CFLAGS="-fPIC" LDFLAGS="-L${TARGET_SYSROOT}${COMMON_DEPENDENCIES_INSTALL_PREFIX}" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_xz
WORKDIR build_xz
ADD public_keys/xz_public_key.gpg xz_public_key.gpg
RUN gpg2 --import xz_public_key.gpg
ARG XZ_VERSION

RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz" > xz.tar.gz
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz.sig" > xz.tar.gz.sig
RUN gpg2 --verify xz.tar.gz.sig xz.tar.gz
RUN tar -xvf xz.tar.gz
WORKDIR "xz-${XZ_VERSION}/build"
RUN ../configure CFLAGS="-fPIC" \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-xzdec --disable-lzmadec \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"
RUN make -j "$(nproc)"
RUN make DESTDIR="/tmp/root" install

FROM build_base as build_zlib_base
WORKDIR build_zlib
ADD public_keys/zlib_public_key.gpg zlib_public_key.gpg
RUN gpg2 --import zlib_public_key.gpg
ARG ZLIB_VERSION
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
WORKDIR zlib-${ZLIB_VERSION}

FROM build_zlib_base as build_zlib_native
RUN CFLAGS="-fPIC" ./configure  --static --prefix=/usr/local
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_zlib_base as build_zlib
RUN CFLAGS="-fPIC" CC="${TARGET}-gcc" ./configure  --static --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_bzip
WORKDIR build_bzip
ADD public_keys/bzip_keyring.gpg bzip_keyring.gpg
RUN gpg2 --import bzip_keyring.gpg
ARG BZIP_VERSION
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz" > bzip2.tar.gz
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz.sig" > bzip2.tar.gz.sig
RUN gpg2 --verify bzip2.tar.gz.sig bzip2.tar.gz
RUN tar -xf "bzip2.tar.gz"
WORKDIR bzip2-${BZIP_VERSION}
RUN make CC="${TARGET}-gcc" install  CFLAGS="-fPIC" PREFIX="/tmp/root"${COMMON_DEPENDENCIES_INSTALL_PREFIX}"" -j "$(nproc)"


FROM build_base as build_util_linux
WORKDIR build_util-linux
ADD public_keys/util_linux_public_key.gpg util_linux_public_key.gpg
RUN gpg2 --import util_linux_public_key.gpg
ARG UTIL_LINUX_VERSION
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.gz" > util-linux.tar.gz
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.sign" > util-linux.tar.sign
RUN gzip -dk util-linux.tar.gz
RUN gpg2 --verify util-linux.tar.sign util-linux.tar
RUN tar -xf util-linux.tar
WORKDIR util-linux-${UTIL_LINUX_VERSION}
RUN CFLAGS="-fPIC" ./configure --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_ncurses_base
WORKDIR build_ncurses
ADD public_keys/gnu-keyring.gpg gnu-keyring.gpg
RUN gpg2 --import gnu-keyring.gpg
ARG NCURSES_VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xvf "ncurses.tar.gz"
WORKDIR ncurses-${NCURSES_VERSION}/build

FROM build_ncurses_base as build_ncurses_native
RUN CFLAGS="-fPIC" ../configure --prefix=/usr/local
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_ncurses_base as build_ncurses_cross
# We have to build and install it nativelly because we need
# the 'tic' tool that is already installed.
COPY --from=build_ncurses_native /tmp/root /
RUN CFLAGS="-fPIC" ../configure --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"
RUN make -j "$(nproc)"
# The strip command from binutils is required for the installation and it seems that
# the configure script can not use string from the cross-toolchain,
# so we just create a symlink.
RUN ln -s "${TARGET_ROOT_PATH}/bin/${TARGET}-strip" "${TARGET_ROOT_PATH}/bin/strip"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_libedit
COPY --from=build_ncurses_cross /tmp/root "${TARGET_SYSROOT}"
WORKDIR build_libedit
ARG LIBEDIT_VERSION_COMMIT
RUN git clone "https://salsa.debian.org/debian/libedit.git"
WORKDIR libedit
RUN git checkout "${LIBEDIT_VERSION_COMMIT}"
WORKDIR build

RUN ../configure \
  CFLAGS="-fPIC -I${TARGET_SYSROOT}/usr/local/include -I${TARGET_SYSROOT}/usr/local/include/ncurses" \
  LDFLAGS="-L${TARGET_SYSROOT}/usr/local/lib -L${TARGET_SYSROOT}/usr/local/lib64" \
    --prefix=""${COMMON_DEPENDENCIES_INSTALL_PREFIX}"" \
    --enable-shared=no \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"

RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_libffi
WORKDIR build_libffi
ARG LIBFFI_VERSION

RUN curl -L "https://github.com/libffi/libffi/releases/download/v${LIBFFI_VERSION}/libffi-${LIBFFI_VERSION}.tar.gz" > libffi.tar.gz
# libffi does not provide any normal way of verifying its source, so every time when we update its
# version we have to manually calculate its checksum and hardcode it there.
RUN echo -n "540fb721619a6aba3bdeef7d940d8e9e0e6d2c193595bc243241b77ff9e93620  libffi.tar.gz" > libffi.tar.gz.sha256
RUN sha256sum -c libffi.tar.gz.sha256
RUN tar -xf libffi.tar.gz
WORKDIR "libffi-${LIBFFI_VERSION}/build"
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory \
    --build="${HOST}" --host="${TARGET}" --target="${TARGET}"

#RUN cat config.log && false
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_openssl_base
WORKDIR build_openssl
ADD public_keys/openssl_public_key.asc openssl_public_key.asc
RUN gpg2 --import openssl_public_key.asc
ARG OPENSSL_INSTALL_PREFIX
ENV OPENSSL_INSTALL_PREFIX=${OPENSSL_INSTALL_PREFIX}
RUN rm ${TARGET_SYSROOT}/lib/libatomic.so*


FROM build_openssl_base as build_openssl_3
ARG OPENSSL_3_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
WORKDIR "openssl-${OPENSSL_3_VERSION}/build"
ADD configure_openssl.sh configure_openssl.sh
RUN bash configure_openssl.sh "3" CC="${TARGET}-gcc" --prefix=${OPENSSL_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw



FROM build_openssl_base as build_openssl_1
ARG OPENSSL_1_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
WORKDIR "openssl-${OPENSSL_1_VERSION}/build"
ADD configure_openssl.sh configure_openssl.sh
RUN bash configure_openssl.sh "1" CC="${TARGET}-gcc" --prefix=${OPENSSL_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM build_openssl_${DEFAULT_OPENSSL_MAJOR_VERSION} as default_openssl


FROM build_base as base_build_python
ADD public_keys/python_pub_key.gpg python_pub_key.gpg
ARG PYTHON_VERSION="3.11.2"

RUN gpg2 --import python_pub_key.gpg
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz

WORKDIR "Python-${PYTHON_VERSION}/build"


FROM base_build_python as build_bootstrap_python
COPY --from=build_zlib_native /tmp/root /

RUN ../configure \
    CFLAGS="-I/usr/local/include" \
    LDFLAGS="-L/usr/local/lib" \
    --enable-shared=no \
    --prefix=/usr/local \
	--with-ensurepip=no
RUN make -j "$(nproc)"
RUN make DESTDIR="/tmp/python" install

FROM base_build_python as build_python_initial
ADD configure_python.sh configure_python.sh
ADD build_python.sh build_python.sh

ARG PYTHON_INSTALL_PREFIX
ARG OPENSSL_INSTALL_PREFIX
ENV PYTHON_INSTALL_PREFIX="${PYTHON_INSTALL_PREFIX}"
ENV OPENSSL_INSTALL_PREFIX="${OPENSSL_INSTALL_PREFIX}"

ENV PKG_CONFIG_DIR=""
ENV PKG_CONFIG_LIBDIR="${TARGET_SYSROOT}/usr/lib/pkgconfig:${TARGET_SYSROOT}/usr/share/pkgconfig"
ENV PKG_CONFIG_SYSROOT_DIR=${TARGET_SYSROOT}

#COPY --from=build_xz /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_zlib /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_bzip /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_util_linux /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_ncurses_cross /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_libedit /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_sqlite /tmp/root ${TARGET_SYSROOT}
#COPY --from=build_libffi /tmp/root ${TARGET_SYSROOT}

COPY --from=build_xz /tmp/root /
COPY --from=build_zlib /tmp/root /
COPY --from=build_bzip /tmp/root /
COPY --from=build_util_linux /tmp/root /
COPY --from=build_ncurses_cross /tmp/root /
COPY --from=build_libedit /tmp/root /
COPY --from=build_sqlite /tmp/root /
COPY --from=build_libffi /tmp/root /

COPY --from=build_zlib_native /tmp/root /
COPY --from=build_bootstrap_python /tmp/python/. /

FROM build_python_initial as build_python_with_openssl_1
COPY --from=build_openssl_1 /tmp/root ${TARGET_SYSROOT}

RUN bash configure_python.sh
RUN bash build_python.sh
RUN make DESTDIR=/tmp/root install


FROM build_python_initial as build_python_with_openssl_3
COPY --from=build_openssl_3 /tmp/root ${TARGET_SYSROOT}

ADD create_toolchain_links.sh create_toolchain_links.sh

RUN bash create_toolchain_links.sh
RUN CC="gcc" AR="ar" LDFLAGS="-static-libgcc" bash configure_python.sh

    #--enable-optimizations --with-lto

RUN bash build_python.sh

RUN make DESTDIR=/tmp/root install

FROM build_python_with_openssl_${DEFAULT_OPENSSL_MAJOR_VERSION} as build_python_with_default_openssl


FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-gnu_x86_64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as  toolchain_x86_64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/aarch64-unknown-linux-gnu_aarch64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_aarch64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/armv7-unknown-linux-gnueabihf_armv7-unknown-linux-gnueabihf:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_armv7-unknown-linux-gnueabihf

FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-musl_x86_64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_x86_64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/aarch64-unknown-linux-musl_aarch64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_aarch64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/armv7-unknown-linux-musleabihf_armv7-unknown-linux-musleabihf:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_armv7-unknown-linux-musleabihf

FROM toolchain_${TARGET} as toolchain
ARG TARGET_ROOT_PATH
RUN mkdir -p "/tmp/root${TARGET_ROOT_PATH}"
RUN cp -a "${TARGET_ROOT_PATH}/." "/tmp/root${TARGET_ROOT_PATH}"


FROM --platform=${IMAGE_PLATFORM} ubuntu:jammy-20230522 as blank_final_base_gnu

FROM --platform=${IMAGE_PLATFORM} alpine:3.18.0 as blank_final_base_musl


FROM  blank_final_base_${TARGET_LIBC} as final_base

ARG PYTHON_INSTALL_PREFIX
ARG OPENSSL_INSTALL_PREFIX
ARG TARGET_ROOT_PATH
ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${TARGET_ROOT_PATH}/bin:${PATH}"
#ENV LD_LIBRARY_PATH="${OPENSSL_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

COPY --from=default_openssl /tmp/root /
COPY --from=toolchain /tmp/root /


FROM final_base as update_pip

COPY --from=default_openssl /tmp/root /
COPY --from=build_python_with_default_openssl /tmp/root /

RUN python3 -m ensurepip
RUN python3 -m pip install --upgrade pip --root /tmp/root

FROM final_base as python_with_openssl_3_with_pip
COPY --from=build_python_with_openssl_3 /tmp/root /tmp/root
COPY --from=update_pip /tmp/root /tmp/root


FROM final_base as python_with_openssl_1_with_pip
COPY --from=build_python_with_openssl_1 /tmp/root /tmp/root
COPY --from=update_pip /tmp/root /tmp/root

FROM python_with_openssl_${DEFAULT_OPENSSL_MAJOR_VERSION}_with_pip as python_with_default_openssl_with_pip


FROM final_base
COPY --from=build_libffi /tmp/root /
COPY --from=python_with_default_openssl_with_pip /tmp/root /
COPY --from=build_libffi /tmp/root /
COPY --from=build_python_with_openssl_3 /tmp/root /opt/tools/openssl_3
COPY --from=build_python_with_openssl_1 /tmp/root /opt/tools/openssl_1
COPY --from=python_with_openssl_3_with_pip /tmp/root /opt/tools/python_with_openssl_3
COPY --from=python_with_openssl_1_with_pip /tmp/root /opt/tools/python_with_openssl_1

