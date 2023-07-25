ARG IMAGE_TYPE

FROM requirement_libs_${TARGETOS}_${TARGETARCH}_${TARGETVARIANT}_context as requirement_libs

FROM base as final-common
COPY --from=requirement_libs /requirements /
COPY --from=agent_filesystem / /

# Optional stage for docker-json.
FROM final-common as final-docker-json
# Nothing to add

# Optional stage for docker-api.
FROM final-common as final-docker-api
# Nothing to add


# Optional stage for docker-syslog.
FROM final-common as final-docker-syslog
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM final-common as final-k8s
ENV SCALYR_STDOUT_SEVERITY ERROR


FROM final-${IMAGE_TYPE} as final
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["python3", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]