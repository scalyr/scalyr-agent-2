ARG BASE_IMAGE_NAME
FROM $BASE_IMAGE_NAME

# Add all files that are involved in the package build process.
RUN rm -rf /scalyr-agent-2
RUN mkdir /scalyr-agent-2
ADD ./scalyr_agent /scalyr-agent-2/scalyr_agent
ADD ./agent_build /scalyr-agent-2/agent_build
ADD ./config /scalyr-agent-2/config
ADD ./docker /scalyr-agent-2/docker
ADD ./monitors /scalyr-agent-2/monitors
ADD ./VERSION /scalyr-agent-2/VERSION
ADD ./CHANGELOG.md /scalyr-agent-2/CHANGELOG.md
ADD ./certs /scalyr-agent-2/certs

# Also add the package test script, so the packager also can make the frozen binary for it.
# This frozen binary later can be used to run package test on systems without python.
ADD ./tests/package_tests/package_test.py /scalyr-agent-2/tests/package_tests/package_test.py

ARG BUILD_COMMAND

# Build the package. Since build options may vary, the build command is prepared outside and is passed there
# though the 'BUILD_COMMAND' argument.
ENV PYTHONPATH="/scalyr-agent-2"
RUN /bin/bash -c "$BUILD_COMMAND"