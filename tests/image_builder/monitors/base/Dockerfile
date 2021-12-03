FROM ubuntu:18.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update -y
RUN apt install -y mysql-server
RUN apt install -y postgresql


USER postgres
RUN service postgresql start && createuser root && createdb root && psql -c "alter user root superuser;" && service postgresql stop
USER root

RUN apt install -y python python3

RUN apt install -y build-essential
RUN apt install -y python-pip python-dev
RUN apt install -y python3-pip python3-dev

RUN apt install -y nginx

ADD requirement-files /scalyr-agent-2/agent_build/requirement-files

COPY dev-requirements.txt /scalyr-agent-2/dev-requirements.txt

RUN python2 -m pip install -r /scalyr-agent-2/dev-requirements.txt
# We need newer version of pip since old version don't support manylinux wheels
RUN python3 -m pip install --upgrade "pip==21.0"
RUN python3 -m pip --version
RUN python3 -m pip install -r /scalyr-agent-2/dev-requirements.txt

WORKDIR /
