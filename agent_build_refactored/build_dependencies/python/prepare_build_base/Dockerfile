ARG ARCH
ARG LIBC

FROM centos:6 as base_x86_64_gnu
ADD centos6/*.repo /etc/yum.repos.d/
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-9 perl-core
RUN echo -e "source /opt/rh/devtoolset-9/enable" >> /root/.bash_env
ENV BASH_ENV="/root/.bash_env"



FROM centos:7 as base_aarch64_gnu
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-9 perl-core

#FROM ubuntu:14.04 as base-armv7-gnu
FROM ubuntu:14.04 as base_armv7_gnu
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository -y ppa:ubuntu-toolchain-r/test
RUN apt-get update && apt-get install -y gcc-9 g++-9
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 1
RUN update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-9 1
RUN apt-get install -y pkg-config make


FROM alpine:3.15 as initial_base_musl
RUN apk add make gcc g++ binutils build-base linux-headers \
    perl bash

FROM initial_base_musl as base_x86_64_musl
FROM initial_base_musl as base_aarch64_musl
FROM initial_base_musl as base_armv7_musl


FROM base_${ARCH}_${LIBC}
SHELL ["/bin/bash", "-c"]
