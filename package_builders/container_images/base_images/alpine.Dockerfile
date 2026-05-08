FROM alpine:3.22.3 as base

FROM base as dependencies-build-base
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
    py3-orjson \
    py3-lz4 \
    py3-zstandard

RUN mkdir -p /tmp/requrements_root/usr/lib/python3.12/site-packages
RUN cp -r /usr/lib/python3.12/site-packages/orjson /tmp/requrements_root/usr/lib/python3.12/site-packages
RUN cp -r /usr/lib/python3.12/site-packages/lz4 /tmp/requrements_root/usr/lib/python3.12/site-packages
RUN cp -r /usr/lib/python3.12/site-packages/zstandard /tmp/requrements_root/usr/lib/python3.12/site-packages

FROM base as runtime-base
RUN apk update && apk add --no-cache python3 py3-pip
