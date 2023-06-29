FROM ubuntu:22.04
RUN apt-get update && apt install -y \
    gnupg2 \
    git \
    tar \
    curl
ADD public_keys /tmp/public_keys
WORKDIR /tmp/download