# This is a "wrapper" dockerfile for the prod image in order to make it suitable for testing.
# Derive from the prod image. It has to be specified as additional contect in the docker build command.
FROM prod_image
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
# Add test-related requirements.
COPY --from=requirement_libs /test_requirements /

# Override entrypoint with including coderage analysys.
CMD ["python3", "-m", "coverage", "run", "--branch", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]
