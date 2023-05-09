FROM prod_image as base

ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
ARG ARCH_DIR_NAME="${TARGETOS}_${TARGETARCH}_${TARGETVARIANT}"

# Add requirements for a test image.
ADD venv_test_libs_root/${ARCH_DIR_NAME} /

# We override the entrypoint command by running agent with enabled coverage.
# When starting a container, the 'TEST_COVERAGE_FILE_PATH' env. variable has to be passed to it in order to specify path for the resulting .coverage file.
CMD [ "/bin/bash", "-c", "usr/share/scalyr-agent-2/bin/python3 -m coverage run --data-file ${TEST_COVERAGE_FILE_PATH} --branch /usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py --no-fork --no-change-user start"]