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

