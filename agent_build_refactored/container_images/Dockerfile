ARG IMAGE_TYPE

FROM requirement_libs_${TARGETOS}_${TARGETARCH}_${TARGETVARIANT}_context as requirement_libs

FROM base_image as base
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
COPY --from=requirement_libs /requirements /
COPY --from=agent_filesystem / /

# Optional stage for docker-json.
FROM base as build-docker-json
# Nothing to add

# Optional stage for docker-api.
FROM base as build-docker-api
# Nothing to add


# Optional stage for docker-syslog.
FROM base as build-docker-syslog
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM base as build-k8s
ENV SCALYR_STDOUT_SEVERITY ERROR


FROM build-${IMAGE_TYPE}
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["python3", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]