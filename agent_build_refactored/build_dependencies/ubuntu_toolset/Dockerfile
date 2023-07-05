FROM essential_ubuntu_tools as base
# Remove system python because we'll install our own Python, which has more predictable version.

COPY --from=build_python_with_openssl_3 / /
COPY --from=build_python_dependencies /openssl_3/. /
ARG PYTHON_INSTALL_PREFIX
ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib"
ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${PATH}"

FROM base as install_dev_requirements
ARG REQUIREMENTS_CONTENT
RUN echo "${REQUIREMENTS_CONTENT}" > /tmp/requirements.txt
COPY --from=build_dev_requirements / /tmp/wheels
RUN python3 -m pip install \
    -r /tmp/requirements.txt \
    --no-index \
    --find-links /tmp/wheels \
    --root /tmp/root


FROM base
COPY --from=install_dev_requirements /tmp/root/. /

RUN gem install "fpm:1.15.1"
# Generate keypair to sign and verify test repos for packages.
RUN gpg2 --batch --passphrase '' --quick-gen-key test default default

