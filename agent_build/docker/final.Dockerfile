ARG BASE_IMAGE_NAME
ARG IMAGE_TYPE_STAGE_NAME
ARG PYTHON_BASE_IMAGE


FROM ${BASE_IMAGE_NAME} as scalyr-build
MAINTAINER Scalyr Inc <support@scalyr.com>

ADD . /scalyr-agent-2

ARG BUILDER_FQDN

# Build the tarball with Agent's files.
RUN AGENT_BUILD_IN_DOCKER=1 python3 /scalyr-agent-2/agent_build/scripts/runner_helper.py ${BUILDER_FQDN} build-container-filesystem --output /tmp/container-fs

WORKDIR /

# Copy result files to a new base stage.
FROM ${PYTHON_BASE_IMAGE} as scalyr-base
MAINTAINER Scalyr Inc <support@scalyr.com>
# Copy Agent's Python dependencies. Those dependencies were built in the base image,
# which is given by 'BASE_IMAGE' arg.
COPY --from=scalyr-build  /tmp/dependencies/ /
# Copy Agent files.
COPY --from=scalyr-build /tmp/container-fs/root /


FROM scalyr-base as build-common
MAINTAINER Scalyr Inc <support@scalyr.com>
# Nothing to add


# Optional stage for docker-syslog.
FROM scalyr-base as build-docker-syslog
MAINTAINER Scalyr Inc <support@scalyr.com>
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM scalyr-base as build-k8s
MAINTAINER Scalyr Inc <support@scalyr.com>
ENV SCALYR_STDOUT_SEVERITY ERROR


# Noraml result image.
FROM build-$IMAGE_TYPE_STAGE_NAME as scalyr-normal
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]