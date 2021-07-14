ARG BASE_IMAGE_NAME
#FROM frozen_binary_and_fpm_builder
FROM $BASE_IMAGE_NAME

# Add all files that are involved in the package build process.
RUN mkdir /scalyr-agent-2
ADD ./scalyr_agent /scalyr-agent-2/scalyr_agent
ADD ./agent_build /scalyr-agent-2/agent_build
ADD ./config /scalyr-agent-2/config
ADD ./docker /scalyr-agent-2/docker
ADD ./monitors /scalyr-agent-2/monitors
ADD ./VERSION /scalyr-agent-2/VERSION

ADD ./tests/distribution_tests/test_scalyr-agent.py /scalyr-agent-2/tests/distribution_tests/test_scalyr-agent.py

ARG ARGV

RUN /bin/bash -c "$ARGV"