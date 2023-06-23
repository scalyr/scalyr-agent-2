ARG PYTHON_INSTALL_PREFIX="/opt/scalyr-agent-2/python3"
ARG OPENSSL_INSTALL_PREFIX="/opt/scalyr-agent-2/openssl"

FROM ubuntu:22.04 as download-base
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt-get update && apt install -y gnupg2 git tar curl
RUN mkdir -p /tmp/source
WORKDIR /tmp/download

FROM download-base as download_python
ADD public_keys/python_pub_key.gpg python_pub_key.gpg
RUN gpg2 --import python_pub_key.gpg
ARG PYTHON_VERSION
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz
RUN mv Python-"${PYTHON_VERSION}" /tmp/source/python



FROM prepare_build_base as build_base
ENV COMMON_DEPENDENCIES_INSTALL_PREFIX="/usr/local"

FROM download-base as download_xz
WORKDIR xz
ADD public_keys/xz_public_key.gpg xz_public_key.gpg
RUN gpg2 --import xz_public_key.gpg
ARG XZ_VERSION
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz" > xz.tar.gz
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz.sig" > xz.tar.gz.sig
RUN gpg2 --verify xz.tar.gz.sig xz.tar.gz
RUN tar -xvf xz.tar.gz
RUN mv xz-${XZ_VERSION} /tmp/source/xz

FROM build_base as build_xz
COPY --from=download_xz /tmp/source /tmp/source
WORKDIR /tmp/source/xz/build
RUN ../configure CFLAGS="-fPIC" \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-xzdec --disable-lzmadec
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download-sqlite
RUN git clone "https://github.com/tcltk/tcl.git"
ARG TCL_VERSION_COMMIT
WORKDIR tcl
RUN git checkout "${TCL_VERSION_COMMIT}"
WORKDIR /tmp/download
RUN mv tcl /tmp/source
RUN git clone "https://github.com/sqlite/sqlite.git"
WORKDIR sqlite
ARG SQLITE_VERSION_COMMIT
RUN git checkout "${SQLITE_VERSION_COMMIT}"
WORKDIR /tmp/download
RUN mv sqlite /tmp/source

FROM build_base as build_sqlite
COPY --from=download-sqlite /tmp/source /tmp/source
WORKDIR /tmp/source/tcl/unix/build
RUN ../configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make install
WORKDIR /tmp/source/sqlite/build
RUN CFLAGS="-fPIC" LDFLAGS="-L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download_zlib
ADD public_keys/zlib_public_key.gpg zlib_public_key.gpg
RUN gpg2 --import zlib_public_key.gpg
ARG ZLIB_VERSION
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
RUN mv zlib-${ZLIB_VERSION} /tmp/source/zlib

FROM build_base as build_zlib
COPY --from=download_zlib /tmp/source /tmp/source
WORKDIR /tmp/source/zlib/build
RUN CFLAGS="-fPIC" ../configure  --static --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM download-base as download_bzip
ADD public_keys/bzip_keyring.gpg bzip_keyring.gpg
RUN gpg2 --import bzip_keyring.gpg
ARG BZIP_VERSION
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz" > bzip2.tar.gz
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz.sig" > bzip2.tar.gz.sig
RUN gpg2 --verify bzip2.tar.gz.sig bzip2.tar.gz
RUN tar -xf "bzip2.tar.gz"
RUN mv bzip2-${BZIP_VERSION} /tmp/source/bzip

FROM build_base as build_bzip
COPY --from=download_bzip /tmp/source /tmp/source
WORKDIR /tmp/source/bzip
RUN make install CFLAGS="-fPIC" PREFIX="/tmp/build${COMMON_DEPENDENCIES_INSTALL_PREFIX}" -j "$(nproc)"
#RUN ls -al /tmp/build && false
RUN tar czf bzip.tar -C /tmp/build .
RUN mkdir -p /tmp/root
RUN cp bzip.tar /tmp/root


FROM download-base as download_util_linux
ADD public_keys/util_linux_public_key.gpg util_linux_public_key.gpg
RUN gpg2 --import util_linux_public_key.gpg
ARG UTIL_LINUX_VERSION
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.gz" > util-linux.tar.gz
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.sign" > util-linux.tar.sign
RUN gzip -dk util-linux.tar.gz
RUN gpg2 --verify util-linux.tar.sign util-linux.tar
RUN tar -xf util-linux.tar
RUN mv util-linux-${UTIL_LINUX_VERSION} /tmp/source/util-linux

FROM build_base as build_util_linux
COPY --from=download_util_linux /tmp/source /tmp/source
WORKDIR /tmp/source/util-linux/build
RUN CFLAGS="-fPIC" ../configure --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download_ncurses
ADD public_keys/gnu-keyring.gpg gnu-keyring.gpg
RUN gpg2 --import gnu-keyring.gpg
ARG NCURSES_VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xvf "ncurses.tar.gz"
RUN mv ncurses-${NCURSES_VERSION} /tmp/source/ncurses

FROM build_base as build_ncurses
COPY --from=download_ncurses /tmp/source /tmp/source
WORKDIR /tmp/source/ncurses/build
RUN CFLAGS="-fPIC" ../configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download_libedit
ARG LIBEDIT_VERSION_COMMIT
RUN git clone "https://salsa.debian.org/debian/libedit.git"
WORKDIR libedit
RUN git checkout "${LIBEDIT_VERSION_COMMIT}"
WORKDIR ..

RUN tar czf libedit.tar -C libedit .
RUN mv libedit.tar /tmp/source

FROM build_base as build_libedit
COPY --from=build_ncurses /tmp/root/. /
COPY --from=download_libedit /tmp/source/libedit.tar /tmp/source/libedit.tar
RUN mkdir -p /tmp/source/libedit
RUN tar xzf /tmp/source/libedit.tar -C /tmp/source/libedit
WORKDIR /tmp/source/libedit/build
RUN echo -e "/usr/local/lib\n/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
RUN ../configure \
  CFLAGS="-fPIC -I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include -I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="-L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib -L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib64" \
  --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
  --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download_libffi
WORKDIR build_libffi
ARG LIBFFI_VERSION
RUN curl -L "https://github.com/libffi/libffi/releases/download/v${LIBFFI_VERSION}/libffi-${LIBFFI_VERSION}.tar.gz" > libffi.tar.gz
# libffi does not provide any normal way of verifying its source, so every time when we update its
# version we have to manually calculate its checksum and hardcode it there.
RUN echo -n "540fb721619a6aba3bdeef7d940d8e9e0e6d2c193595bc243241b77ff9e93620  libffi.tar.gz" > libffi.tar.gz.sha256
RUN sha256sum -c libffi.tar.gz.sha256
RUN tar -xf libffi.tar.gz
RUN mv libffi-${LIBFFI_VERSION} /tmp/source/libffi

FROM build_base as build_libffi
COPY --from=download_libffi /tmp/source /tmp/source
WORKDIR /tmp/source/libffi/build
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download-base as download_openssl_3
ADD public_keys/openssl_public_key.asc openssl_public_key.asc
RUN gpg2 --import openssl_public_key.asc
ARG OPENSSL_3_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_3_VERSION} /tmp/source/openssl

FROM download-base as download_openssl_1
ADD public_keys/openssl_public_key.asc openssl_public_key.asc
RUN gpg2 --import openssl_public_key.asc
ARG OPENSSL_1_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_1_VERSION} /tmp/source/openssl

FROM build_base as build_openssl_base

FROM build_openssl_base as build_openssl_3
COPY --from=download_openssl_3 /tmp/source /tmp/source
WORKDIR /tmp/source/openssl/build
ADD configure_openssl.sh configure_openssl.sh
ARG OPENSSL_INSTALL_PREFIX
ARG ARCH
ARG LIBC
RUN ARCH="${ARCH}" LIBC="${LIBC}" bash configure_openssl.sh "3" --prefix=${OPENSSL_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw



FROM build_openssl_base as build_openssl_1
COPY --from=download_openssl_1 /tmp/source /tmp/source
WORKDIR /tmp/source/openssl/build
ADD configure_openssl.sh configure_openssl.sh
ARG OPENSSL_INSTALL_PREFIX
ARG ARCH
ARG LIBC
RUN ARCH="${ARCH}" LIBC="${LIBC}" bash configure_openssl.sh "1" --prefix=${OPENSSL_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM build_base as base_build_python
COPY --from=build_xz /tmp/root/. /
COPY --from=build_sqlite /tmp/root/. /
COPY --from=build_zlib /tmp/root/. /
COPY --from=build_bzip /tmp/root/bzip.tar /tmp/root/bzip.tar
RUN tar xfzv /tmp/root/bzip.tar -C / .
RUN rm /tmp/root/bzip.tar
COPY --from=build_util_linux /tmp/root/. /
COPY --from=build_ncurses /tmp/root/. /
COPY --from=build_libedit /tmp/root/. /
COPY --from=build_libffi /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
ARG OPENSSL_INSTALL_PREFIX
ENV PYTHON_INSTALL_PREFIX="${PYTHON_INSTALL_PREFIX}"
ENV OPENSSL_INSTALL_PREFIX="${OPENSSL_INSTALL_PREFIX}"
ENV LD_LIBRARY_PATH="${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
ENV LD_LIBRARY_PATH="${OPENSSL_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

COPY --from=download_python /tmp/source /tmp/source
WORKDIR /tmp/source/python/build

ADD configure_python.sh configure_python.sh

FROM base_build_python as build_python_with_openssl_3
COPY --from=build_openssl_3 /tmp/root/. /
RUN bash configure_python.sh
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM base_build_python as build_python_with_openssl_1
COPY --from=build_openssl_1 /tmp/root/. /
RUN bash configure_python.sh
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM ubuntu:22.04 as wrapped_python

SHELL ["/bin/bash", "-c"]
ARG RESULT_DIR=/tmp/root
COPY --from=build_openssl_1 /tmp/root /tmp/openssl_1
COPY --from=build_openssl_3 /tmp/root /tmp/openssl_3
COPY --from=build_python_with_openssl_1 /tmp/root /tmp/python_with_openssl_1
COPY --from=build_python_with_openssl_3 /tmp/root /tmp/python_with_openssl_3
COPY --from=build_python_with_openssl_3 /tmp/root ${RESULT_DIR}

ARG PYTHON_INSTALL_PREFIX
ARG PYTHON_X_Y_VERSION=3.11

# Create result version of the openssl directory
ARG OPENSSL_INSTALL_PREFIX

ARG PYTHON_LIB_DIR="${RESULT_DIR}${PYTHON_INSTALL_PREFIX}/lib"
RUN mkdir -p "${PYTHON_LIB_DIR}"
RUN cp "/tmp/openssl_3${OPENSSL_INSTALL_PREFIX}/lib"/*.so* "${PYTHON_LIB_DIR}"


ENV PYTHON_OPENSSL_LIBDIR="${PYTHON_LIB_DIR}/openssl"
RUN mkdir -p "${PYTHON_OPENSSL_LIBDIR}"

ENV LIB_DYNLOAD_DIR_PATH="${PYTHON_INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}/lib-dynload"

ENV PYTHON_OPENSSL_1_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/1/bindings"
RUN mkdir -p "${PYTHON_OPENSSL_1_BINDINGS}"

RUN cp "/tmp/python_with_openssl_1${LIB_DYNLOAD_DIR_PATH}/"_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_1_BINDINGS}"

ENV PYTHON_OPENSSL_3_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/3/bindings"
RUN mkdir -p "${PYTHON_OPENSSL_3_BINDINGS}"
RUN cp "/tmp/python_with_openssl_3${LIB_DYNLOAD_DIR_PATH}"/_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_3_BINDINGS}"

ENV PYTHON_OPENSSL_EMBEDDED_DIR="${PYTHON_OPENSSL_LIBDIR}/embedded"
RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}"
RUN ln -s "../3/bindings" "${PYTHON_OPENSSL_EMBEDDED_DIR}/bindings"
RUN ln -s "../../../../openssl/lib" "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"

ADD files/python3 "${RESULT_DIR}/${PYTHON_INSTALL_PREFIX}/bin/python3"

ARG PYTHON_VENV_LIB_DIR="${PYTHON_LIB_DIR}/python${PYTHON_X_Y_VERSION}/venv"
RUN mv "${PYTHON_VENV_LIB_DIR}/__main__.py" "${PYTHON_VENV_LIB_DIR}/__main_original__.py"
ADD files/venv/__main_wrapper__.py "${PYTHON_VENV_LIB_DIR}/__main__.py"

FROM build_base as python_with_pip
COPY --from=wrapped_python /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip

COPY --from=wrapped_python /tmp/root /tmp/root
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root


FROM build_base as python_with_pip
COPY --from=wrapped_python /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip

COPY --from=wrapped_python /tmp/root /tmp/root
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root


