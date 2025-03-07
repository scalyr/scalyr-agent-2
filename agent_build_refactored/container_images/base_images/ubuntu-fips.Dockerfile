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
# We upgrade current packages in order to keep everything up to date, including security updates.
RUN DEBIANFRONTEND=noninteractive apt-get update && \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV OPENSSL_CONF /etc/ssl/openssl.cnf.fips
ENV SCALYR_ALLOW_HTTP_MONITORS false
