FROM ubuntu:16.04
ENV DEBIAN_FRONTEND noninteractive
MAINTAINER Scalyr Inc <support@scalyr.com>
RUN apt-get update && \
    apt-get install -y python && \
    apt-get clean
COPY scalyr-docker-agent.tar.gz /tmp/
RUN tar -C / -zxf /tmp/scalyr-docker-agent.tar.gz && \
  rm /tmp/scalyr-docker-agent.tar.gz

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]
