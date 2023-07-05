FROM ubuntu:22.04
RUN DEBIAN_FRONTEND="noninteractive" \
    apt-get update ; \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
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
    aptly && \
    apt-get autoremove --yes && \
    rm -rf /var/lib/apt/lists/*