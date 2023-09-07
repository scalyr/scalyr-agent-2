ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

FROM base as dependencies_build_base
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip  \
    python3-dev \
    rustc \
    cargo && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*



FROM base as runtime_base
# We upgrade current packages in order to keep everything up to date, including security updates.
RUN DEBIANFRONTEND=noninteractive apt-get update && \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    python3 && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
