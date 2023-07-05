FROM ubuntu:22.04
RUN DEBIAN_FRONTEND="noninteractive" \
    apt-get update ; \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    curl \
    gnupg2 \
    git \
    tar && \
    apt-get autoremove --yes && \
    rm -rf /var/lib/apt/lists/*