FROM download_source_base as download
#ADD public_keys/zlib_public_key.gpg zlib_public_key.gpg
RUN gpg2 --import /tmp/public_keys/zlib_public_key.gpg
ARG VERSION
RUN curl -L "https://github.com/madler/zlib/releases/download/v${VERSION}/zlib-${VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L "https://github.com/madler/zlib/releases/download/v${VERSION}/zlib-${VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
RUN mv zlib-${VERSION} /tmp/source

FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure  --static --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /