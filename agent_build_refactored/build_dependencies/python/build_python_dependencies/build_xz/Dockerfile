FROM download_source_base as download
RUN gpg2 --import /tmp/public_keys/xz_public_key.gpg
ARG VERSION
RUN curl -L "https://tukaani.org/xz/xz-${VERSION}.tar.gz" > xz.tar.gz
RUN curl -L "https://tukaani.org/xz/xz-${VERSION}.tar.gz.sig" > xz.tar.gz.sig
RUN gpg2 --verify xz.tar.gz.sig xz.tar.gz
RUN tar -xvf xz.tar.gz
RUN mv xz-${VERSION} /tmp/source

FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN ../configure CFLAGS="-fPIC" \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared=no --disable-xzdec --disable-lzmadec
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /