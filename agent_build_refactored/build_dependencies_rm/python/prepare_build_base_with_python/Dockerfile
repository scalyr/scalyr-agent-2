FROM prepare_build_base as base
COPY --from=build_python_with_openssl_3 / /
COPY --from=build_python_dependencies /openssl_3/. /
ARG INSTALL_PREFIX
ARG PYTHON_DEPENDENCIES_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${PYTHON_DEPENDENCIES_INSTALL_PREFIX}/lib"
ENV PATH="${INSTALL_PREFIX}/bin:${PATH}"
ENV PKG_CONFIG_PATH="${PYTHON_DEPENDENCIES_INSTALL_PREFIX}/lib64/pkgconfig:${PYTHON_DEPENDENCIES_INSTALL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH}"


FROM base as build
ARG REQUIREMENTS_CONTENT
RUN echo "${REQUIREMENTS_CONTENT}" > /tmp/requirements.txt
COPY --from=build_dev_requirements / /tmp/wheels
RUN python3 -m pip install \
    -r /tmp/requirements.txt \
    --no-index \
    --find-links /tmp/wheels \
    --no-warn-script-location \
    --root-user-action=ignore \
    --root /tmp/root

FROM base
COPY --from=build /tmp/root/. /




