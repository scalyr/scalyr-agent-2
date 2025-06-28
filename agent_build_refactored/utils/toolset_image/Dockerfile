FROM ubuntu:22.04
RUN DEBIAN_FRONTEND="noninteractive" \
    apt-get update && \
    apt-get install -y \
    binutils \
    tar \
    gnupg2 \
    ruby  \
    ruby-dev  \
    rubygems \
    openssh-client \
    reprepro \
    createrepo-c \
    aptly \
    rpm && \
    apt-get autoremove --yes && \
    rm -rf /var/lib/apt/lists/*

RUN gem install "fpm:1.15.1"

RUN gpg2 --batch --passphrase '' --quick-gen-key test default default
