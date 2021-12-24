# Final Scalyr Agent docker image that uses the previously built base image.
# NOTE: multi-stage builds require Docker 17.05 or greater

# Type of the image build, e.g: docker-json, docker-syslog, k8s
ARG BUILD_TYPE

# Name of the base image to use.
ARG BASE_IMAGE

ARG MODE="normal"


FROM $BASE_IMAGE as scalyr-build
MAINTAINER Scalyr Inc <support@scalyr.com>

# If specified then the package build command will produce additional debug logging.
ARG AGENT_BUILD_DEBUG
ENV AGENT_BUILD_DEBUG=$AGENT_BUILD_DEBUG
# Special env. variable that will enable addional logging info about that command runs in docker.
ENV AGENT_BUILD_IN_DOCKER=1
# e.g. k8s, docker-json
ARG BUILD_TYPE
# e.g. k8s-buster, docker-json-buster, k8s-alpine
ARG BUILDER_NAME
ADD . /scalyr-agent-2

# Build the tarball with Agent's files.
RUN python3 /scalyr-agent-2/build_package_new.py ${BUILDER_NAME} --only-filesystem-tarball /tmp/build/scalyr-agent.tar.gz

# Extract tarball to the special place that can be reused by next stages.
WORKDIR /tmp/container-fs
RUN tar -xf /tmp/build/scalyr-agent.tar.gz

WORKDIR /

# Copy result files to a new base stage.
FROM python:3.8.10-slim as scalyr-base
MAINTAINER Scalyr Inc <support@scalyr.com>
# Copy Agent's Python dependencies. Those dependencies were built in the base image,
# which is given by 'BASE_IMAGE' arg.
COPY --from=scalyr-build  /tmp/dependencies/ /
# Copy Agent files.
COPY --from=scalyr-build /tmp/container-fs /


# Optional stage for docker-json.
FROM scalyr-base as build-docker-json
MAINTAINER Scalyr Inc <support@scalyr.com>
# Nothing to add

# Optional stage for docker-api.
FROM scalyr-base as build-docker-api
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
FROM build-$BUILD_TYPE as scalyr-normal
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]


# Result image stage for testing.
FROM build-$BUILD_TYPE as scalyr-testing
MAINTAINER Scalyr Inc <support@scalyr.com>
# Since test version of the image uses coverage, add command that runs the Agent with enabled coverage.
CMD ["coverage", "run", "--branch", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py", "--no-fork", "--no-change-user", "start"]

# Use stage with needed mode as a final image.
FROM scalyr-$MODE as scalyr
MAINTAINER Scalyr Inc <support@scalyr.com>
