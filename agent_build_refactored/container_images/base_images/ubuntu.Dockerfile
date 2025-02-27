ARG BASE_IMAGE
FROM ${BASE_IMAGE} as base

FROM base as dependencies_build_base
ENV DEBIANFRONTEND=noninteractive
RUN apt update
RUN apt install -y python3 python3-pip python3-dev
RUN apt install -y rustc
RUN apt install -y cargo
RUN apt-get autoremove --yes
RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*


FROM base as runtime_base

