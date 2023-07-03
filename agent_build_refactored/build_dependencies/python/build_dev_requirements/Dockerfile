#FROM download_source_base as download_rust
FROM prepare_build_base as base
ARG RUST_VERSION
ARG RUST_PLATFORM
ADD agent_build_refactored/build_dependencies/python/build_dev_requirements/rust-key.gpg.ascii /tmp/public_keys/rust-key.gpg.ascii
RUN gpg2 --import /tmp/public_keys/rust-key.gpg.ascii
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz.asc" > rust.tar.gz.asc
RUN gpg --verify rust.tar.gz.asc rust.tar.gz
RUN tar -xzf rust.tar.gz
WORKDIR rust-${RUST_VERSION}-${RUST_PLATFORM}

ARG INSTALL_PREFIX
ARG COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib"
ENV PATH="${INSTALL_PREFIX}/bin:/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib64/pkgconfig:${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH}"
COPY --from=build_python_dependencies /libffi/. /
COPY --from=build_python_dependencies /zlib/. /
COPY --from=build_python_dependencies /openssl_3/. /
COPY --from=build_python_with_openssl_3 / /
RUN ./install.sh

ADD dev-requirements-new.txt /tmp/requirements.txt

RUN python3 -m pip wheel -r /tmp/requirements.txt --wheel-dir /tmp/wheels

FROM scratch
COPY --from=base /tmp/wheels/. /


