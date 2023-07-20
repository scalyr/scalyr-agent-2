ARG BASE_DISTRO

FROM ubuntu:22.04 as base_ubuntu

FROM python:3.8.16-alpine as base_alpine

FROM base_ubuntu as build_base_ubuntu
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y \
    python3 \
    python3-pip  \
    python3-dev \
    rustc \
    cargo

FROM base_alpine as build_base_alpine
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

FROM build_base_${BASE_DISTRO} as build_requirement_libs
RUN python3 -m pip install --upgrade setuptools pip --root /tmp/requrements_root
RUN cp -a /tmp/requrements_root/. /
ARG AGENT_REQUIREMENTS
RUN echo "${AGENT_REQUIREMENTS}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/requrements_root
ARG TEST_REQUIREMENTS
RUN echo "${TEST_REQUIREMENTS}" > /tmp/test_requirments.txt
RUN python3 -m pip install -r /tmp/test_requirments.txt --root /tmp/test_requrements_root

FROM scratch as requirement_libs
COPY --from=build_requirement_libs /tmp/requrements_root /requirements
COPY --from=build_requirement_libs /tmp/test_requrements_root /test_requirements

FROM base_ubuntu as final_image_base_ubuntu
# We upgrade current packages in order to keep everything up to date, including security updates.
RUN DEBIANFRONTEND=noninteractive apt-get update && \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    python3 && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


FROM base_alpine as final_image_base_alpine

FROM final_image_base_${BASE_DISTRO} as final_image_base