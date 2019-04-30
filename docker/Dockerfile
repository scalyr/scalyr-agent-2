FROM python:2.7-alpine3.9 as scalyr
MAINTAINER Scalyr Inc <support@scalyr.com>

RUN apk --update add --virtual build-dependencies build-base python-dev gcc \
  && pip --no-cache-dir install ujson \
  && apk del build-dependencies

COPY scalyr-docker-agent.tar.gz /tmp/
RUN tar --no-same-owner -C / -zxf /tmp/scalyr-docker-agent.tar.gz && \
  rm /tmp/scalyr-docker-agent.tar.gz

EXPOSE 601/tcp

# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]
