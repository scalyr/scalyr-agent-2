FROM python:2-wheezy

MAINTAINER Scalyr Inc <support@scalyr.com>


WORKDIR /tmp

RUN git init && \
  git config --local user.name "Scalyr" && git config --local user.email support@scalyr.com && \
  git clone -b release git://github.com/scalyr/scalyr-agent-2.git

RUN pip install mock==2.0.0
RUN chmod -R +x scalyr-agent-2
WORKDIR scalyr-agent-2
