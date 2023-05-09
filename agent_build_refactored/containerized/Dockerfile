ARG BASE_DISTRO
ARG IMAGE_TYPE

FROM ubuntu:22.04 as base_ubuntu
RUN apt-get update ; apt-get dist-upgrade -y
RUN apt-get install -y openssl
RUN apt-get clean

FROM alpine:3.17 as base_alpine
RUN apk --no-cache add bash openssl

FROM base_${BASE_DISTRO} as base

ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
ARG ARCH_DIR_NAME="${TARGETOS}_${TARGETARCH}_${TARGETVARIANT}"

ADD python/${ARCH_DIR_NAME} /
ADD venv/${ARCH_DIR_NAME} /
ADD agent_filesystem_root /


# Optional stage for docker-json.
FROM base as docker-json
# Nothing to add


# Optional stage for docker-api.
FROM base as docker-api
# Nothing to add


# Optional stage for docker-syslog.
FROM base as docker-syslog
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM base as k8s
ENV SCALYR_STDOUT_SEVERITY ERROR


# Use stage with needed image type as a final image.
FROM ${IMAGE_TYPE}
MAINTAINER Scalyr Inc <support@scalyr.com>
CMD ["/usr/share/scalyr-agent-2/bin/python3", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py", "--no-fork", "--no-change-user", "start"]