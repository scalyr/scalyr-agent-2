# base image that creates all necessary dependencies for
# the scalyr-agent
# NOTE: multi-stage builds require Docker 17.05 or greater

# Type of the image build, e.g: docker-json, docker-syslog, k8s
ARG BUILD_TYPE

# Agent run mode. Can be 'normal' or 'coverage' to enable code coverage tool.
ARG MODE="normal"

# Build image files and dependencies.
FROM python:3.8.10-slim as scalyr-build
MAINTAINER Scalyr Inc <support@scalyr.com>

RUN apt-get update && apt-get install -y build-essential git tar

ADD docker/requirements.txt /tmp/requirments.txt

# install python dependencies
RUN pip --no-cache-dir install --root /tmp/dependencies -r /tmp/requirments.txt

ARG CACHE_BUST=1
ARG AGENT_BUILD_DEBUG
# If specified then the package build command will produce additional debug logging.
ENV AGENT_BUILD_DEBUG=$AGENT_BUILD_DEBUG
# Special env. variable that will enable addional logging info about that command runs in docker.
ENV AGENT_BUILD_IN_DOCKER=1
ARG BUILD_TYPE
ADD . /scalyr-agent-2

RUN python3 /scalyr-agent-2/build_package_new.py $BUILD_TYPE --only-filesystem-tarball /tmp/build

WORKDIR /tmp/container-fs
RUN tar -xf /tmp/build/scalyr-agent.tar.gz

WORKDIR /

# Copy result files to a new base stage.
FROM python:3.8.10-slim as scalyr-base
MAINTAINER Scalyr Inc <support@scalyr.com>

COPY --from=scalyr-build  /tmp/dependencies/ /
COPY --from=scalyr-build /tmp/container-fs /


# Optional stage for docker json.
FROM scalyr-base as build-docker-json
MAINTAINER Scalyr Inc <support@scalyr.com>
# Nothing to add

# Optional stage for docker api.
FROM scalyr-base as build-docker-api
MAINTAINER Scalyr Inc <support@scalyr.com>
# Nothing to add


# Optional stage for docker syslog.
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


# Noraml result image
FROM build-$BUILD_TYPE as scalyr-normal
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]


# Result image with enabled coverage (for tests).
FROM build-$BUILD_TYPE as scalyr-with-coverage
MAINTAINER Scalyr Inc <support@scalyr.com>

RUN python3 -m pip install coverage==4.5.4
CMD ["coverage", "run", "--branch", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py", "--no-fork", "--no-change-user", "start"]

# Use stage with needed mode as a final image.
FROM scalyr-$MODE as scalyr
MAINTAINER Scalyr Inc <support@scalyr.com>


