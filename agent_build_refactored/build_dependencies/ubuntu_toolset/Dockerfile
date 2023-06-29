FROM ubuntu:22.04
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt-get update && apt install -y \
    gnupg2 \
    git \
    tar \
    curl \
    python3 \
    python3-dev \
    python3-pip \
    build-essential \
    ruby  \
    ruby-dev  \
    rubygems \
    reprepro \
    createrepo-c \
    aptly

ADD dev-requirements-new.txt /tmp/dev-requirements-new.txt
RUN python3 -m pip install -r /tmp/dev-requirements-new.txt

RUN gem install "fpm:1.15.1"