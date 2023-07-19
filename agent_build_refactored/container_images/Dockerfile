ARG BASE_DISTRO
ARG IMAGE_TYPE

FROM base_image as base_ubuntu
# We upgrade current packages in order to keep everything up to date, including security updates.
RUN DEBIANFRONTEND=noninteractive apt-get update && \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    python3 && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


FROM base_image as base_alpine

#FROM ${TARGETOS}_${TARGETARCH}_${TARGETVARIANT}_requirements as requirements

FROM base_${BASE_DISTRO} as base
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
COPY --from=requirements /${TARGETOS}_${TARGETARCH}_${TARGETVARIANT} /
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