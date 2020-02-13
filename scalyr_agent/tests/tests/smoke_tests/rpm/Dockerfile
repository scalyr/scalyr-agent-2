FROM amazonlinux

ARG PYTHON_VERSION=python3

RUN yum install -y initscripts $PYTHON_VERSION

WORKDIR /scalyr_build

ADD ./scalyr_agent_package.rpm /scalyr_build

RUN ln -s -f /usr/bin/$PYTHON_VERSION /usr/bin/python

RUN rpm -i scalyr_agent_package.rpm