FROM ubuntu:16.04
ENV DEBIAN_FRONTEND noninteractive
MAINTAINER Scalyr Inc <support@scalyr.com>
RUN apt-get update && apt-get install -y \
  apt-transport-https \ 
  python \
  wget && \
  apt-get clean
RUN mkdir -p /tmp/scalyr && \
  cd /tmp/scalyr && \
  wget -q https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh && \
  chmod 755 ./install-scalyr-agent-2.sh && \
  ./install-scalyr-agent-2.sh --verbose && \
  cd / && \
  rm -rf /tmp/scalyr
CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]