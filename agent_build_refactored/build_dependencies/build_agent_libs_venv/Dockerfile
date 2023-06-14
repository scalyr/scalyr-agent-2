ARG INSTALL_RUST_STAGE_NAME

FROM prepare_build_environment as build_base

FROM build_base as install_rust
WORKDIR /tmp/install_rust

ARG RUST_VERSION
ARG RUST_PLATFORM
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
RUN tar -xzf rust.tar.gz
WORKDIR "rust-${RUST_VERSION}-${RUST_PLATFORM}"
RUN ./install.sh

WORKDIR ../..

FROM build_base as install_rust_from_package_manager_gnu
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt update && apt install -y rust

FROM build_base as install_rust_from_package_manager_musl
RUN apk add rust

FROM ${INSTALL_RUST_STAGE_NAME} as install_rust_from_package_manager
COPY --from=build_python /tmp/root/. /
ARG PYTHON_INSTALL_PREFIX

ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${PATH}"
RUN python3 -m venv /var/opt/scalyr-agent-2/venv
ARG REQUIREMENTS
RUN echo "${REQUIREMENTS}" > /tmp/requirements.txt
RUN /var/opt/scalyr-agent-2/venv/bin/python3 -m pip wheel -r /tmp/requirements.txt --root /tmp/root
