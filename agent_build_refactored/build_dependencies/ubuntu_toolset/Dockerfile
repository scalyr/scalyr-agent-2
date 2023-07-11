FROM essential_ubuntu_tools as base
RUN DEBIAN_FRONTEND="noninteractive" \
    apt-get update ; \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    build-essential \
    ruby  \
    ruby-dev  \
    rubygems \
    reprepro \
    createrepo-c \
    aptly \
    rpm  \
    python3  \
    python3-pip  \
    python3-dev && \
    apt-get autoremove --yes && \
    rm -rf /var/lib/apt/lists/*

#COPY --from=build_python_with_openssl_3 / /
#COPY --from=build_python_dependencies /openssl_3/. /
#ARG PYTHON_INSTALL_PREFIX
#ARG PYTHON_DEPENDENCIES_INSTALL_PREFIX
#ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${PYTHON_DEPENDENCIES_INSTALL_PREFIX}/lib"
#ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${PATH}"

FROM base as install_dev_requirements
ARG REQUIREMENTS_CONTENT
RUN echo "${REQUIREMENTS_CONTENT}" > /tmp/requirements.txt
RUN python3 -m pip install \
    --no-warn-script-location \
    -r /tmp/requirements.txt \
    --root /tmp/root


FROM base
COPY --from=install_dev_requirements /tmp/root/. /

RUN gem install "fpm:1.15.1"
# Generate keypair to sign and verify test repos for packages.
RUN gpg2 --batch --passphrase '' --quick-gen-key test default default

