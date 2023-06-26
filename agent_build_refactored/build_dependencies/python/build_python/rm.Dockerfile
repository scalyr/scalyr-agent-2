ARG PYTHON_INSTALL_PREFIX="/opt/scalyr-agent-2/python3"
ARG OPENSSL_INSTALL_PREFIX
ARG OPENSSL_MAJOR_VERSION


FROM download_base as download_python
ADD public_keys/python_pub_key.gpg python_pub_key.gpg
RUN gpg2 --import python_pub_key.gpg
ARG PYTHON_VERSION
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz
RUN mv Python-"${PYTHON_VERSION}" /tmp/source


FROM prepare_build_base as build_base
ENV COMMON_DEPENDENCIES_INSTALL_PREFIX="/usr/local"
RUN mkdir -p /tmp/source

#FROM build_base as build_xz
#COPY --from=download_sources /tmp/source/xz /tmp/source/xz
#WORKDIR /tmp/source/xz/build
#RUN ../configure CFLAGS="-fPIC" \
#    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
#    --enable-shared=no --disable-xzdec --disable-lzmadec
#RUN make -j "$(nproc)"
#RUN make DESTDIR=/tmp/root install

FROM build_base as build_sqlite
COPY --from=download_sources /tmp/source/tcl /tmp/source/tcl
WORKDIR /tmp/source/tcl/unix/build
RUN ../configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make install
COPY --from=download_sources /tmp/source/sqlite /tmp/source/sqlite
WORKDIR /tmp/source/sqlite/build
RUN CFLAGS="-fPIC" LDFLAGS="-L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_zlib
COPY --from=download_sources /tmp/source/zlib /tmp/source/zlib
WORKDIR /tmp/source/zlib/build
RUN CFLAGS="-fPIC" ../configure  --static --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM build_base as build_bzip
COPY --from=download_sources /tmp/source/bzip /tmp/source/bzip
WORKDIR /tmp/source/bzip
RUN make install CFLAGS="-fPIC" PREFIX="/tmp/build${COMMON_DEPENDENCIES_INSTALL_PREFIX}" -j "$(nproc)"
RUN tar czf bzip.tar -C /tmp/build .
RUN mkdir -p /tmp/root
RUN cp bzip.tar /tmp/root

FROM build_base as build_util_linux
COPY --from=download_sources /tmp/source/util-linux /tmp/source/util-linux
WORKDIR /tmp/source/util-linux/build
RUN CFLAGS="-fPIC" ../configure --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_ncurses
COPY --from=download_sources /tmp/source/ncurses /tmp/source/ncurses
WORKDIR /tmp/source/ncurses/build
RUN CFLAGS="-fPIC" ../configure --prefix=${COMMON_DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_libedit

COPY --from=build_ncurses /tmp/root/. /
COPY --from=download_sources /tmp/source/libedit.tar /tmp/source/libedit.tar
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


FROM build_base as build_libffi
COPY --from=download_sources /tmp/source/libffi /tmp/source/libffi
WORKDIR /tmp/source/libffi/build
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${COMMON_DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM build_base as build_openssl_base

#FROM build_openssl_base as build_openssl_3
#COPY --from=download_sources /tmp/source/openssl_3 /tmp/source/openssl_3
#WORKDIR /tmp/source/openssl_3/build
#ADD configure_openssl.sh configure_openssl.sh
#ARG OPENSSL_INSTALL_PREFIX
#ARG ARCH
#ARG LIBC
#RUN ARCH="${ARCH}" LIBC="${LIBC}" bash configure_openssl.sh "3" --prefix=${OPENSSL_INSTALL_PREFIX}
#RUN make -j "$(nproc)"
#RUN make DESTDIR=/tmp/root install_sw
#
#
#
#FROM build_openssl_base as build_openssl_1
#COPY --from=download_sources /tmp/source/openssl_1 /tmp/source/openssl_1
#WORKDIR /tmp/source/openssl_1/build
#ADD configure_openssl.sh configure_openssl.sh
#ARG OPENSSL_INSTALL_PREFIX
#ARG ARCH
#ARG LIBC
#RUN ARCH="${ARCH}" LIBC="${LIBC}" bash configure_openssl.sh "1" --prefix=${OPENSSL_INSTALL_PREFIX}
#RUN make -j "$(nproc)"
#RUN make DESTDIR=/tmp/root install_sw

FROM build_openssl_${OPENSSL_MAJOR_VERSION} as build_openssl

FROM prepare_build_base as build
COPY --from=build_xz /tmp/xz.tar /tmp/xz.tar
#COPY --from=build_sqlite /tmp/root/. /
#COPY --from=build_zlib /tmp/root/. /
#COPY --from=build_bzip /tmp/root/bzip.tar /tmp/root/bzip.tar
#RUN tar xfzv /tmp/root/bzip.tar -C / .
#RUN rm /tmp/root/bzip.tar
#COPY --from=build_util_linux /tmp/root/. /
#COPY --from=build_ncurses /tmp/root/. /
#COPY --from=build_libedit /tmp/root/. /
#COPY --from=build_libffi /tmp/root/. /

ARG PYTHON_INSTALL_PREFIX
ARG OPENSSL_INSTALL_PREFIX
ENV PYTHON_INSTALL_PREFIX="${PYTHON_INSTALL_PREFIX}"
ENV OPENSSL_INSTALL_PREFIX="${OPENSSL_INSTALL_PREFIX}"
ENV LD_LIBRARY_PATH="${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
ENV LD_LIBRARY_PATH="${OPENSSL_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

COPY --from=download_python /tmp/source /tmp/source
WORKDIR /tmp/source/build

ADD configure_python.sh configure_python.sh
#COPY --from=build_openssl / /
RUN bash configure_python.sh
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /

#FROM base_build_python as build_python_with_openssl_3
#COPY --from=build_openssl_3 /tmp/root/. /
#RUN bash configure_python.sh
#RUN make -j "$(nproc)"
#RUN make DESTDIR=/tmp/root install
#
#FROM base_build_python as build_python_with_openssl_1
#COPY --from=build_openssl_1 /tmp/root/. /
#RUN bash configure_python.sh
#RUN make -j "$(nproc)"
#RUN make DESTDIR=/tmp/root install




#FROM ubuntu:22.04 as wrapped_python
#
#SHELL ["/bin/bash", "-c"]
#ARG RESULT_DIR=/tmp/root
##COPY --from=build_openssl_1 /tmp/root /tmp/openssl_1
#COPY --from=build_openssl / /
#COPY --from=build_python_with_openssl_1 /tmp/root /tmp/python_with_openssl_1
#COPY --from=build_python_with_openssl_3 /tmp/root /tmp/python_with_openssl_3
#COPY --from=build_python_with_openssl_3 /tmp/root ${RESULT_DIR}
#
#ARG PYTHON_INSTALL_PREFIX
#ARG PYTHON_X_Y_VERSION=3.11
#
## Create result version of the openssl directory
#ARG OPENSSL_INSTALL_PREFIX
#
#ARG PYTHON_LIB_DIR="${RESULT_DIR}${PYTHON_INSTALL_PREFIX}/lib"
#RUN mkdir -p "${PYTHON_LIB_DIR}"
#RUN cp "/tmp/openssl_3${OPENSSL_INSTALL_PREFIX}/lib"/*.so* "${PYTHON_LIB_DIR}"
#
#
#ENV PYTHON_OPENSSL_LIBDIR="${PYTHON_LIB_DIR}/openssl"
#RUN mkdir -p "${PYTHON_OPENSSL_LIBDIR}"
#
#ENV LIB_DYNLOAD_DIR_PATH="${PYTHON_INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}/lib-dynload"
#
#ENV PYTHON_OPENSSL_1_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/1/bindings"
#RUN mkdir -p "${PYTHON_OPENSSL_1_BINDINGS}"
#
#RUN cp "/tmp/python_with_openssl_1${LIB_DYNLOAD_DIR_PATH}/"_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_1_BINDINGS}"
#
#ENV PYTHON_OPENSSL_3_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/3/bindings"
#RUN mkdir -p "${PYTHON_OPENSSL_3_BINDINGS}"
#RUN cp "/tmp/python_with_openssl_3${LIB_DYNLOAD_DIR_PATH}"/_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_3_BINDINGS}"
#
#ENV PYTHON_OPENSSL_EMBEDDED_DIR="${PYTHON_OPENSSL_LIBDIR}/embedded"
#RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}"
#RUN ln -s "../3/bindings" "${PYTHON_OPENSSL_EMBEDDED_DIR}/bindings"
#RUN ln -s "../../../../openssl/lib" "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
#
#ADD files/python3 "${RESULT_DIR}/${PYTHON_INSTALL_PREFIX}/bin/python3"
#
#ARG PYTHON_VENV_LIB_DIR="${PYTHON_LIB_DIR}/python${PYTHON_X_Y_VERSION}/venv"
#RUN mv "${PYTHON_VENV_LIB_DIR}/__main__.py" "${PYTHON_VENV_LIB_DIR}/__main_original__.py"
#ADD files/venv/__main_wrapper__.py "${PYTHON_VENV_LIB_DIR}/__main__.py"
#
#FROM build_base as python_with_pip
#COPY --from=wrapped_python /tmp/root/. /
#
#ARG PYTHON_INSTALL_PREFIX
#RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip
#
#COPY --from=wrapped_python /tmp/root /tmp/root
#RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root
#
#
#FROM build_base as python_with_pip
#
#COPY --from=wrapped_python /tmp/root/. /
#
#ARG PYTHON_INSTALL_PREFIX
#RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip
#
#COPY --from=wrapped_python /tmp/root /tmp/root
#RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root

