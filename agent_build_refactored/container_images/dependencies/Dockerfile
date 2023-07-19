ARG BASE_DISTRO

FROM base_image as base_ubuntu
# We upgrade current packages in order to keep everything up to date, including security updates.
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y \
    python3 \
    python3-pip  \
    python3-dev \
    rustc \
    cargo

RUN python3 -m pip install --upgrade setuptools pip --root /tmp/requrements_root
RUN cp -a /tmp/requrements_root/. /

FROM base_image as base_alpine
RUN apk update && apk add --virtual build-dependencies \
    binutils \
    build-base \
    linux-headers \
    gcc \
    g++ \
    make \
    curl \
    python3-dev \
    patchelf \
    git \
    bash \
    rust \
    cargo

FROM base_${BASE_DISTRO} as base_v7_variant
SHELL ["linux32", "/bin/bash", "-c"]

FROM base_${BASE_DISTRO} as base__variant
SHELL ["/bin/bash", "-c"]

FROM base_${TARGETVARIANT}_variant as build_requirements
ARG AGENT_REQUIREMENTS
RUN echo "${AGENT_REQUIREMENTS}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/requrements_root


FROM scratch
COPY --from=build_requirements /tmp/requrements_root/. /
