ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

FROM base as dependencies_build_base
RUN apk update && apk add --no-cache \
    --virtual build-dependencies \
    binutils \
    build-base \
    linux-headers \
    gcc \
    g++ \
    make \
    curl \
    python3 \
    python3-dev \
    py3-pip \
    patchelf \
    git \
    bash \
    rust \
    cargo \
    py3-orjson

RUN mkdir -p /tmp/requrements_root/usr/lib/python3.11/site-packages
RUN cp -r ./usr/lib/python3.11/site-packages/orjson /tmp/requrements_root/usr/lib/python3.11/site-packages

FROM base as runtime_base
RUN apk update && apk add --no-cache python3 py3-pip
