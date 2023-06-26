FROM download_base as download
#ADD public_keys/openssl_public_key.asc openssl_public_key.asc
RUN gpg2 --import /tmp/public_keys/openssl_public_key.asc
ARG VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${VERSION} /tmp/source

FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ADD configure_openssl.sh configure_openssl.sh
ARG INSTALL_PREFIX
ARG MAJOR_VERSION
ARG ARCH
ARG LIBC
RUN ARCH="${ARCH}" LIBC="${LIBC}" MAJOR_VERSION="${MAJOR_VERSION}" \
    bash configure_openssl.sh --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw

FROM scratch
COPY --from=build /tmp/root/. /