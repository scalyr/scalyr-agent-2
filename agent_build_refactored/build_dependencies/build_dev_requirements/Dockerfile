ARG RUST_SOURCE
ARG LIBC


FROM prepare_build_base as  base
COPY --from=build_python / /
ARG PYTHON_INSTALL_PREFIX
ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${PATH}"
RUN python3 -m agent_python3_config set preferred_openssl embedded
RUN python3 -m agent_python3_config initialize

FROM download_base as download_rust
ARG RUST_VERSION
ARG RUST_PLATFORM
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
RUN tar -xzvf rust.tar.gz
RUN mv rust-${RUST_VERSION}-${RUST_PLATFORM} /tmp/rust

FROM base as rust_from_site
COPY --from=download_rust /tmp/rust /tmp/rust
ENV PATH="/usr/local/bin:/root/.cargo/bin:${PATH}"
#ENV PKG_CONFIG_PATH="/usr/local/lib64/pkgconfig:/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH}"
WORKDIR /tmp/rust
RUN ./install.sh


FROM alpine:3.17 as rust_from_package_manager_musl
RUN apk add rust cargo bash binutils build-base linux-headers

FROM ubuntu as rust_from_package_manager_gnu
RUN apk add rust

FROM rust_from_package_manager_${LIBC} as rust_from_package_manager
COPY --from=build_python / /
ARG PYTHON_INSTALL_PREFIX
ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:${PATH}"
RUN python3 -m agent_python3_config set preferred_openssl embedded
RUN python3 -m agent_python3_config initialize

FROM rust_from_${RUST_SOURCE} as rust_based_requirements_wheels
#RUN cargo install cargo-update -v
ARG RUST_BASED_REQUIREMENTS
RUN echo "${RUST_BASED_REQUIREMENTS}" > /tmp/rust_based_requirements.txt
#RUN python3 -m pip install -r /tmp/orjson_requirements.txt --root /tmp/root
RUN python3 -m pip wheel -r /tmp/rust_based_requirements.txt --wheel-dir /tmp/wheels

FROM base as non_rust_based_requirements_wheels
ARG NON_RUST_BASED_REQUIREMENTS
RUN echo "${NON_RUST_BASED_REQUIREMENTS}" > /tmp/non_rust_based_requirements.txt
COPY --from=build_libffi / /
COPY --from=build_zlib / /
#RUN python3 -m pip install -r /tmp/non_rust_requirements.txt --root /tmp/root
RUN python3 -m pip wheel -r /tmp/non_rust_based_requirements.txt --wheel-dir /tmp/wheels


FROM scratch
COPY --from=rust_based_requirements_wheels /tmp/wheels /
COPY --from=non_rust_based_requirements_wheels /tmp/wheels /