# Base image that creates all necessary dependencies for the scalyr-agent docker image.
# NOTE: multi-stage builds require Docker 17.05 or greater

## Suffix for the python dockerhub image. For now can be:
##   - 'slim' for debian based image
##   - 'alpine' for alpine based image.
#ARG BASE_IMAGE_SUFFIX

ARG PYTHON_BASE_IMAGE

# Install dependency packages for debian.
FROM ${PYTHON_BASE_IMAGE} as scalyr-base-dependencies
MAINTAINER Scalyr Inc <support@scalyr.com>

ARG DISTRO_NAME

## Workaround for weird build failure on Circle CI, see
## https://github.com/docker/buildx/issues/495#issuecomment-995503425 for details
#RUN ln -s /usr/bin/dpkg-split /usr/sbin/dpkg-split
#RUN ln -s /usr/bin/dpkg-deb /usr/sbin/dpkg-deb
#RUN ln -s /bin/rm /usr/sbin/rm
#RUN ln -s /bin/tar /usr/sbin/tar
ADD agent_build/docker/install-base-dependencies.sh agent_build/docker/install-base-dependencies.sh
RUN DISTRO_NAME=${DISTRO_NAME} agent_build/docker/install-base-dependencies.sh


FROM scalyr-base-dependencies as scalyr-python-libs-build-dependencies

# Install packages that are required to build agent python dependency libs.
ADD agent_build/docker/install-python-libs-build-dependencies.sh agent_build/docker/install-python-libs-build-dependencies.sh
RUN DISTRO_NAME=${DISTRO_NAME} agent_build/docker/install-python-libs-build-dependencies.sh


ADD agent_build/docker/install-python-libs.sh agent_build/docker/install-python-libs.sh
ADD agent_build/requirement-files/docker-image-requirements.txt agent_build/requirement-files/docker-image-requirements.txt
ADD agent_build/requirement-files/compression-requirements.txt agent_build/requirement-files/compression-requirements.txt
ADD agent_build/requirement-files/main-requirements.txt agent_build/requirement-files/main-requirements.txt
ARG TARGETVARIANT
ARG COVERAGE_VERSION
# Install agent python denendency libs.
RUN DISTRO_NAME=${DISTRO_NAME} TARGETVARIANT=${TARGETVARIANT} COVERAGE_VERSION=${COVERAGE_VERSION} agent_build/docker/install-python-libs.sh

# Create a final image with only dependnencies that will be required by final image.
FROM scalyr-base-dependencies

# Copy Agent's Python dependencies, so they also can be used in the final image build.
COPY --from=scalyr-python-libs-build-dependencies  /tmp/dependencies/ /tmp/dependencies/
COPY --from=scalyr-python-libs-build-dependencies  /tmp/test-image-dependencies /tmp/test-image-dependencies
WORKDIR /
