FROM ubuntu:18.04

RUN apt update -y
RUN apt install -y mysql-server

RUN apt install -y python python3

RUN apt install -y build-essential
RUN apt install -y python-pip python-dev
RUN apt install -y python3-pip python3-dev

RUN apt install -y nginx

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY ./agent_source /agent_source

WORKDIR /

