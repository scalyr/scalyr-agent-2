FROM prepare_build_base as base
COPY --from=build_python_with_openssl_3 / /
COPY --from=build_python_dependencies /openssl_3/. /
ARG INSTALL_PREFIX
ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib"
ENV PATH="${INSTALL_PREFIX}/bin:/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib64/pkgconfig:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH}"

ADD dev-requirements-new.txt /tmp/requirements.txt

COPY --from=build_dev_requirements / /tmp/wheels
RUN python3 -m pip install \
    -r /tmp/requirements.txt \
    --no-index \
    --find-links /tmp/wheels


