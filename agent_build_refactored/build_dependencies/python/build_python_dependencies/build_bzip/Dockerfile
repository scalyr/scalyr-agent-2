FROM download_source_base as download
RUN gpg2 --import /tmp/public_keys/bzip_keyring.gpg
ARG VERSION
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${VERSION}.tar.gz" > bzip2.tar.gz
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${VERSION}.tar.gz.sig" > bzip2.tar.gz.sig
RUN gpg2 --verify bzip2.tar.gz.sig bzip2.tar.gz
RUN tar -xf "bzip2.tar.gz"
RUN mv bzip2-${VERSION} /tmp/source


FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source
ARG INSTALL_PREFIX
RUN make install CFLAGS="-fPIC" PREFIX="/tmp/root${INSTALL_PREFIX}" -j "$(nproc)"

FROM scratch
COPY --from=build /tmp/root/. /