FROM prepare_build_base as base
COPY --from=build_python / /
ARG INSTALL_PREFIX
ENV PATH="${INSTALL_PREFIX}/bin:${PATH}"
RUN python3 -m agent_python3_config set preferred_openssl embedded
RUN python3 -m agent_python3_config initialize

FROM base
COPY --from=build_dev_requirements / /tmp/dev_requirements_wheels
ARG ALL_REQUIREMENTS
RUN echo "${ALL_REQUIREMENTS}" > /tmp/all_requirements.txt
RUN python3 -m pip install -r /tmp/all_requirements.txt --no-index --find-links /tmp/dev_requirements_wheels

