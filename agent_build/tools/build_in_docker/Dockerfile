# This is a special Dockerfile that allows to run custom command during the docker build.
# It is also posible to specify particular stage to specify set of files that are needed to add to the build context.

ARG BASE_IMAGE_NAME
ARG BUILD_STAGE

# This stage is used in building of the deployment steps (agent_build/tools/environemt_deployments.py).
# It expects that the base image contains all needed files to perform the step.
FROM $BASE_IMAGE_NAME as stage-step-build
ARG WORK_DIR="/"
WORKDIR $WORK_DIR
# Set this special env. variable for additional logging.
ENV IN_DOCKER=1
# Do nothing all files have to be in the base image.


# This stage is used in the agent package build.
FROM $BASE_IMAGE_NAME as stage-build
RUN rm -rf /scalyr-agent-2
# Add all files that are involved in the package build process.
ADD ./agent_build /scalyr-agent-2/agent_build
ADD ./scalyr_agent /scalyr-agent-2/scalyr_agent
ADD ./config /scalyr-agent-2/config
ADD ./docker /scalyr-agent-2/docker
ADD ./monitors /scalyr-agent-2/monitors
ADD ./VERSION /scalyr-agent-2/VERSION
ADD ./CHANGELOG.md /scalyr-agent-2/CHANGELOG.md
ADD ./certs /scalyr-agent-2/certs
ADD ./build_package.py /scalyr-agent-2/build_package.py


# This stage is used in the building frozen binary from the package test runner.
# This frozen binary later can be used to run package tests on systems without python.
FROM $BASE_IMAGE_NAME as stage-test
RUN rm -rf /scalyr-agent-2
ADD ./agent_build /scalyr-agent-2/agent_build
ADD ./tests/package_tests/ /scalyr-agent-2/tests/package_tests/


# Pick only specified stage.
FROM stage-$BUILD_STAGE

# Run command
ARG COMMAND
ENV PYTHONPATH="/scalyr-agent-2"
RUN /bin/bash -c "$COMMAND"