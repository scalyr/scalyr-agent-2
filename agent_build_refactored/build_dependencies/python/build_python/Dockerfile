ARG OPENSSL_MAJOR_VERSION
ARG LIBC

#FROM download_source_base as download
#RUN gpg2 --import /tmp/public_keys/python_pub_key.gpg
#ARG PYTHON_VERSION
#RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
#RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
#RUN gpg --verify python.tgz.asc python.tgz
#RUN tar -xf python.tgz
#RUN mv Python-"${PYTHON_VERSION}" /tmp/source

FROM scratch as build_openssl
COPY --from=build_python_dependencies /openssl_${OPENSSL_MAJOR_VERSION}/. /

#FROM build_openssl_${OPENSSL_MAJOR_VERSION} as build_openssl

#FROM prepare_build_base as build_base
#COPY --from=download /tmp/source /tmp/source
#COPY --from=build_xz / /
#COPY --from=build_sqlite / /
#COPY --from=build_zlib / /
#COPY --from=build_bzip / /
#COPY --from=build_util_linux / /
#COPY --from=build_ncurses / /
#COPY --from=build_libedit / /
#COPY --from=build_libffi / /
#COPY --from=build_openssl / /
#ARG INSTALL_PREFIX
#ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
#ENV LD_LIBRARY_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
#WORKDIR /tmp/source/build
#ADD configure_python.sh configure_python.sh

FROM prepare_build_base as build_python
#COPY --from=build_xz / /
#COPY --from=build_sqlite / /
#COPY --from=build_zlib / /
#COPY --from=build_bzip / /
#COPY --from=build_util_linux / /
#COPY --from=build_ncurses / /
#COPY --from=build_libedit / /
#COPY --from=build_libffi / /
#COPY --from=build_openssl / /
ARG OPENSSL_MAJOR_VERSION
COPY --from=build_python_dependencies /bzip/. /
COPY --from=build_python_dependencies /libedit/. /
COPY --from=build_python_dependencies /libffi/. /
COPY --from=build_python_dependencies /ncurses/. /
COPY --from=build_python_dependencies /openssl_${OPENSSL_MAJOR_VERSION}/. /
COPY --from=build_python_dependencies /sqlite/. /
COPY --from=build_python_dependencies /util_linux/. /
COPY --from=build_python_dependencies /xz/. /
COPY --from=build_python_dependencies /zlib/. /


ARG INSTALL_PREFIX
ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

COPY --from=download_sources /python /tmp/source
WORKDIR /tmp/source/build
#ADD configure_python.sh configure_python.sh
#RUN INSTALL_PREFIX="${INSTALL_PREFIX}" \
#    COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}" \
#    bash configure_python.sh

RUN ../configure \
  CFLAGS="-I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include -I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="${LDFLAGS} -L${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
    --with-openssl="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${INSTALL_PREFIX}" \
	--with-ensurepip=no

RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

#RUN readelf -d /tmp/root/opt/scalyr-agent-2/python3/lib/python3.11/lib-dynload/_ssl.cpython-311-x86_64-linux-gnu.so && false

# Copy sqlite shared library because it's dfficult to make it compiled statically.
# TODO: But it would be good to create static.
COPY --from=build_python_dependencies /sqlite /tmp/sqlite
RUN cp /tmp/sqlite${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib/*.so* /tmp/root${INSTALL_PREFIX}/lib

# Remove cache files.
RUN find "/tmp/root${INSTALL_PREFIX}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# install built python to the current system
RUN cp -a /tmp/root/. /

RUN ${INSTALL_PREFIX}/bin/python3 -m ensurepip
# Install upgraded pip version in the final python root.
RUN ${INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root


FROM scratch
COPY --from=build_python /tmp/root/. /


##FROM build_base as build_python_with_openssl_3
##COPY --from=build_openssl_3 / /
##RUN bash configure_python.sh
##RUN make -j "$(nproc)"
##RUN make DESTDIR=/tmp/root install
#
#
#FROM ubuntu:22.04 as post_build_base
#SHELL ["/bin/bash", "-c"]
#
#FROM post_build_base as modify_python_files
#ARG RESULT_DIR=/tmp/root
#COPY --from=build_python_with_openssl_3 /tmp/root ${RESULT_DIR}
#ARG INSTALL_PREFIX
#ARG PYTHON_X_Y_VERSION
#ADD files/bin/python3 "${RESULT_DIR}/${INSTALL_PREFIX}/bin"
#ARG PYTHON_LIB_PYTHON_X_Y_DIR="${RESULT_DIR}${INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}"
#ARG PYTHON_VENV_LIB_DIR="${PYTHON_LIB_PYTHON_X_Y_DIR}/venv"
##RUN mv "${PYTHON_VENV_LIB_DIR}/__main__.py" "${PYTHON_VENV_LIB_DIR}/__main_original__.py"
##ADD files/venv/__main_wrapper__.py "${PYTHON_VENV_LIB_DIR}/__main__.py"
#RUN mkdir -p "${RESULT_DIR}/${INSTALL_PREFIX}/etc"
#
#
#FROM post_build_base as python_with_system_openssl
#COPY --from=modify_python_files /tmp/root /tmp/root
#
#FROM post_build_base as python_with_switchable_openssl
#ARG RESULT_DIR=/tmp/root
#COPY --from=build_openssl_3 / /tmp/openssl_3
#COPY --from=modify_python_files /tmp/root /tmp/python_with_openssl_3
#COPY --from=modify_python_files /tmp/root ${RESULT_DIR}
#
#ARG INSTALL_PREFIX
#ARG PYTHON_X_Y_VERSION
#ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
#
#ARG PYTHON_LIB_DIR="${RESULT_DIR}${INSTALL_PREFIX}/lib"
#RUN mkdir -p "${PYTHON_LIB_DIR}"
#
#
#ENV PYTHON_OPENSSL_LIBDIR="${PYTHON_LIB_DIR}/openssl"
#RUN mkdir -p "${PYTHON_OPENSSL_LIBDIR}"
#
#ARG LIB_DYNLOAD_DIR_PATH="${INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}/lib-dynload"
#
## Remove this code block, when OpenSSL 1 reaches EOL.
## REMOVE OPENSSL 1
#COPY --from=build_openssl_1 / /tmp/openssl_1
#COPY --from=build_python_with_openssl_1 /tmp/root /tmp/python_with_openssl_1
#ARG PYTHON_OPENSSL_1_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/1/bindings"
#RUN mkdir -p "${PYTHON_OPENSSL_1_BINDINGS}"
#RUN cp "/tmp/python_with_openssl_1${LIB_DYNLOAD_DIR_PATH}/"_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_1_BINDINGS}"
## REMOVE OPENSSL 1
#
#ARG PYTHON_OPENSSL_3_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/3/bindings"
#RUN mkdir -p "${PYTHON_OPENSSL_3_BINDINGS}"
#RUN cp "/tmp/python_with_openssl_3${LIB_DYNLOAD_DIR_PATH}"/_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_3_BINDINGS}"
#
#ARG PYTHON_OPENSSL_EMBEDDED_DIR="${PYTHON_OPENSSL_LIBDIR}/embedded"
#RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}"
#RUN ln -s "../3/bindings" "${PYTHON_OPENSSL_EMBEDDED_DIR}/bindings"
##RUN ln -s "../../../../openssl/lib" "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
#RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
#RUN cp "/tmp/openssl_3${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib"/*.so* "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
#
#ARG PYTHON_LIB_PYTHON_X_Y_DIR="${RESULT_DIR}${INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}"
#ADD files/agent_python3_config.py "${PYTHON_LIB_PYTHON_X_Y_DIR}"
#
#
#FROM python_with_${OPENSSL_TYPE}_openssl as  python_with_openssl
#
#FROM post_build_base as python_with_sqlite
#COPY --from=build_sqlite / /tmp/sqlite
#COPY --from=python_with_openssl /tmp/root /tmp/root
#ARG INSTALL_PREFIX
#ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
#RUN cp /tmp/sqlite${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib/*.so* /tmp/root${INSTALL_PREFIX}/lib
#
#
#FROM prepare_build_base as python_with_pip
#COPY --from=build_openssl_3 / /
#COPY --from=python_with_sqlite /tmp/root/. /
#
#ARG INSTALL_PREFIX
#ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
#ENV LD_LIBRARY_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
#RUN ${INSTALL_PREFIX}/bin/python3 -m ensurepip
#
#COPY --from=python_with_sqlite /tmp/root/. /tmp/root
#RUN ${INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip --root /tmp/root
#
#
#FROM scratch
#COPY --from=python_with_pip /tmp/root/. /