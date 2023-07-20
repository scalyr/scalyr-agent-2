#FROM prod_image as build
#ARG REQUIREMENTS_FILE_CONTENT
#RUN echo "${REQUIREMENTS_FILE_CONTENT}" > /tmp/requirements.txt
#RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/root
#
#FROM scratch
#COPY --from=build /tmp/root /

FROM prod_image
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
COPY --from=requirement_libs /test_requirements /

CMD ["python3", "-m", "coverage", "run", "--branch", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]
