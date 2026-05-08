FROM ubuntu:24.04 as base

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Ubuntu 24.04 comes with Python 3.12 as default. So, download and
# set Python 3.13 as default.
RUN apt-get update \
    && apt-get install -y software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.13 \
    && apt-get autoremove --yes \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# This sets Python 3.13 as the default 'python3' command
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.13 1

FROM base as dependencies-builder-base
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update  \
    && apt-get install -y python3.13-dev python3.13-venv rustc cargo \
    && python3.13 -m ensurepip --upgrade \
    && apt-get autoremove --yes \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

FROM base as runtime-base
# We upgrade current packages in order to keep everything up to date, including security updates.
# Installing ca-certificates populates /etc/ssl/certs but requires openssl (only libssl installed by default).
RUN DEBIANFRONTEND=noninteractive apt-get update \
    && apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests \
    && apt-get install -y ca-certificates \
    && apt-get autoremove --yes \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
