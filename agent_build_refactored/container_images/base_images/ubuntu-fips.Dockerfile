ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

FROM base as dependencies_build_base
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y \
    rustc \
    cargo && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*



FROM base as runtime_base
ENV OPENSSL_CONF /etc/ssl/openssl.cnf.fips
ENV SCALYR_ALLOW_HTTP_MONITORS false
