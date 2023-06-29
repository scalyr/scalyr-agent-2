FROM download_source_base as download_rust
ARG RUST_VERSION
ARG RUST_PLATFORM
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
RUN tar -xzf rust.tar.gz
RUN mv rust-${RUST_VERSION}-${RUST_PLATFORM} /tmp/rust

FROM prepare_build_base as base
ARG INSTALL_PREFIX
ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib"
ENV PATH="${INSTALL_PREFIX}/bin:/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib64/pkgconfig:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH}"
COPY --from=build_libffi / /
COPY --from=build_zlib / /
COPY --from=build_openssl_3 / /
COPY --from=build_python_with_openssl_3 / /
COPY --from=download_rust /tmp/rust /tmp/rust
WORKDIR /tmp/rust
RUN ./install.sh

ADD dev-requirements-new.txt /tmp/requirements.txt

RUN python3 -m pip wheel -r /tmp/requirements.txt --wheel-dir /tmp/wheels

FROM scratch
COPY --from=base /tmp/wheels/. /


