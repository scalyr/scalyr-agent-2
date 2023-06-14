ARG PYTHON_INSTALL_PREFIX="/opt/scalyr-agent-2/python3"
ARG OPENSSL_INSTALL_PREFIX="/opt/scalyr-agent-2/openssl"

FROM prepare_build_environment as build_base
ENV COMMON_DEPENDENCIES_INSTALL_PREFIX="/usr/local"

FROM build_base as build_sqlite

# Build dependency tcl first
WORKDIR build_tcl
RUN git clone "https://github.com/tcltk/tcl.git"
WORKDIR tcl
ARG TCL_VERSION_COMMIT
RUN git checkout "${TCL_VERSION_COMMIT}"
WORKDIR unix
RUN ./configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make install

WORKDIR ../build_sqlite
RUN git clone "https://github.com/sqlite/sqlite.git"
WORKDIR sqlite
ARG SQLITE_VERSION_COMMIT
RUN git checkout "${SQLITE_VERSION_COMMIT}"
WORKDIR build
RUN apk add tcl
RUN CFLAGS="-fPIC" LDFLAGS="-L${COMMON_DEPENDENCIES_INSTALL_PREFIX}" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"
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
    --enable-shared=no --disable-xzdec --disable-lzmadec
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install



FROM build_base as build_zlib
WORKDIR build_zlib
ADD public_keys/zlib_public_key.gpg zlib_public_key.gpg
RUN gpg2 --import zlib_public_key.gpg
ARG ZLIB_VERSION
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
WORKDIR zlib-${ZLIB_VERSION}
RUN CFLAGS="-fPIC" ./configure  --static --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
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
RUN make install  CFLAGS="-fPIC" PREFIX="/tmp/root${COMMON_DEPENDENCIES_INSTALL_PREFIX}" -j "$(nproc)"


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
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_ncurses
WORKDIR build_ncurses
ADD public_keys/gnu-keyring.gpg gnu-keyring.gpg
RUN gpg2 --import gnu-keyring.gpg
ARG NCURSES_VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xvf "ncurses.tar.gz"
WORKDIR ncurses-${NCURSES_VERSION}/build
RUN CFLAGS="-fPIC" ../configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_libedit
COPY --from=build_ncurses /tmp/root/. /
WORKDIR build_libedit
ARG LIBEDIT_VERSION_COMMIT
RUN git clone "https://salsa.debian.org/debian/libedit.git"
WORKDIR libedit
RUN git checkout "${LIBEDIT_VERSION_COMMIT}"
WORKDIR build

RUN ../configure \
  CFLAGS="-fPIC -I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include -I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="-L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib -L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib64" \
  --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
  --enable-shared=no
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
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_openssl_base
WORKDIR build_openssl
ADD public_keys/openssl_public_key.asc openssl_public_key.asc
RUN gpg2 --import openssl_public_key.asc
ARG OPENSSL_INSTALL_PREFIX
ENV OPENSSL_INSTALL_PREFIX="${OPENSSL_INSTALL_PREFIX}"

FROM build_openssl_base as build_openssl_3
ARG OPENSSL_3_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
WORKDIR "openssl-${OPENSSL_3_VERSION}/build"
ADD configure_openssl.sh configure_openssl.sh
RUN bash configure_openssl.sh "3" --prefix=${OPENSSL_INSTALL_PREFIX}
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
RUN bash configure_openssl.sh "1" --prefix=${OPENSSL_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw



FROM build_base as base_build_python
ADD public_keys/python_pub_key.gpg python_pub_key.gpg
ARG PYTHON_VERSION

RUN gpg2 --import python_pub_key.gpg
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz

WORKDIR "Python-${PYTHON_VERSION}/build"

COPY --from=build_xz /tmp/root/. /
COPY --from=build_sqlite /tmp/root/. /
COPY --from=build_zlib /tmp/root/. /
COPY --from=build_bzip /tmp/root/. /
COPY --from=build_util_linux /tmp/root/. /
COPY --from=build_ncurses /tmp/root/. /
COPY --from=build_libedit /tmp/root/. /
COPY --from=build_libffi /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
ARG OPENSSL_INSTALL_PREFIX
ENV PYTHON_INSTALL_PREFIX="${PYTHON_INSTALL_PREFIX}"
ENV OPENSSL_INSTALL_PREFIX="${OPENSSL_INSTALL_PREFIX}"

ADD configure_python.sh configure_python.sh



FROM base_build_python as build_python_with_openssl_1
COPY --from=build_openssl_1 /tmp/root/. /

RUN bash configure_python.sh
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM base_build_python as build_python_with_openssl_3
COPY --from=build_openssl_3 /tmp/root/. /

# LDFLAGS="-static-libgcc"
RUN bash configure_python.sh
    #--enable-optimizations --with-lto

RUN make -j "$(nproc)"

RUN make DESTDIR=/tmp/root install

FROM build_base as wrapped_python

ARG RESULT_DIR=/tmp/root
COPY --from=build_openssl_1 /tmp/root /tmp/openssl_1
COPY --from=build_openssl_3 /tmp/root /tmp/openssl_3
COPY --from=build_python_with_openssl_1 /tmp/root /tmp/python_with_openssl_1
COPY --from=build_python_with_openssl_3 /tmp/root /tmp/python_with_openssl_3
COPY --from=build_python_with_openssl_3 /tmp/root ${RESULT_DIR}



ARG PYTHON_INSTALL_PREFIX
ARG PYTHON_X_Y_VERSION

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
ADD venv/__main_wrapper__.py "${PYTHON_VENV_LIB_DIR}/__main__.py"

FROM build_base as python_with_pip
COPY --from=wrapped_python /tmp/root /tmp/root
COPY --from=wrapped_python /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root

#FROM build_base
#COPY --from=wrapped_python /tmp/root/. /

