FROM download_base as download
#ADD public_keys/util_linux_public_key.gpg util_linux_public_key.gpg
RUN gpg2 --import /tmp/public_keys/util_linux_public_key.gpg
ARG VERSION
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${VERSION}/util-linux-${VERSION}.tar.gz" > util-linux.tar.gz
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${VERSION}/util-linux-${VERSION}.tar.sign" > util-linux.tar.sign
RUN gzip -dk util-linux.tar.gz
RUN gpg2 --verify util-linux.tar.sign util-linux.tar
RUN tar -xf util-linux.tar
RUN mv util-linux-${VERSION} /tmp/source

FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix="${INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /