FROM prepare_build_base as modify_python_files
ARG RESULT_DIR=/tmp/root
COPY --from=build_openssl_3 / /tmp/openssl_3
COPY --from=build_python_with_openssl_3 /tmp/root/. /tmp/python_with_openssl_3
COPY --from=build_python_with_openssl_3 /tmp/root/. ${RESULT_DIR}
ARG PYTHON_INSTALL_PREFIX
#ADD files/bin/python3 "${RESULT_DIR}/${PYTHON_INSTALL_PREFIX}/bin"
RUN mkdir -p "${RESULT_DIR}/${PYTHON_INSTALL_PREFIX}/etc"

ARG PYTHON_X_Y_VERSION
ARG COMMON_PYTHON_DEPENDENCY_PYTHON_INSTALL_PREFIX

ARG PYTHON_LIB_DIR="${RESULT_DIR}${PYTHON_INSTALL_PREFIX}/lib"
#RUN mkdir -p "${PYTHON_LIB_DIR}"

ARG PYTHON_OPENSSL_LIBDIR="${PYTHON_LIB_DIR}/openssl"
RUN mkdir -p "${PYTHON_OPENSSL_LIBDIR}"

ARG LIB_DYNLOAD_DIR_PATH="${PYTHON_INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}/lib-dynload"

# Remove this code block, when OpenSSL 1 reaches EOL.
# REMOVE OPENSSL 1
COPY --from=build_openssl_1 / /tmp/openssl_1
COPY --from=build_python_with_openssl_1 /tmp/root/. /tmp/python_with_openssl_1
ARG PYTHON_OPENSSL_1_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/1/bindings"
RUN mkdir -p "${PYTHON_OPENSSL_1_BINDINGS}"
RUN cp "/tmp/python_with_openssl_1${LIB_DYNLOAD_DIR_PATH}/"_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_1_BINDINGS}"
# REMOVE OPENSSL 1

ARG PYTHON_OPENSSL_3_BINDINGS="${PYTHON_OPENSSL_LIBDIR}/3/bindings"
RUN mkdir -p "${PYTHON_OPENSSL_3_BINDINGS}"
RUN cp "/tmp/python_with_openssl_3${LIB_DYNLOAD_DIR_PATH}"/_{ssl,hashlib}.cpython-*-*-*-*.so "${PYTHON_OPENSSL_3_BINDINGS}"

ARG PYTHON_OPENSSL_EMBEDDED_DIR="${PYTHON_OPENSSL_LIBDIR}/embedded"
RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}"
RUN ln -s "../3/bindings" "${PYTHON_OPENSSL_EMBEDDED_DIR}/bindings"
#RUN ln -s "../../../../openssl/lib" "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
RUN mkdir -p "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"
RUN cp "/tmp/openssl_3${COMMON_PYTHON_DEPENDENCY_PYTHON_INSTALL_PREFIX}/lib"/*.so* "${PYTHON_OPENSSL_EMBEDDED_DIR}/libs"

ARG PYTHON_LIB_PYTHON_X_Y_DIR="${RESULT_DIR}${PYTHON_INSTALL_PREFIX}/lib/python${PYTHON_X_Y_VERSION}"
ADD files/agent_python3_config.py "${PYTHON_LIB_PYTHON_X_Y_DIR}"

FROM scratch
COPY --from=modify_python_files /tmp/root/. /