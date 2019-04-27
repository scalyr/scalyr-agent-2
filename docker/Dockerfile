FROM python:2.7-alpine3.9 as scalyr
MAINTAINER Scalyr Inc <support@scalyr.com>
COPY scalyr-docker-agent.tar.gz /tmp/
RUN tar --no-same-owner -C / -zxf /tmp/scalyr-docker-agent.tar.gz && \
  rm /tmp/scalyr-docker-agent.tar.gz

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]
