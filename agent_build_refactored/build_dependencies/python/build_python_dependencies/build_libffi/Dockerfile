FROM download_base as download
ARG VERSION
RUN curl -L "https://github.com/libffi/libffi/releases/download/v${VERSION}/libffi-${VERSION}.tar.gz" > libffi.tar.gz
# libffi does not provide any normal way of verifying its source, so every time when we update its
# version we have to manually calculate its checksum and hardcode it there.
RUN echo -n "540fb721619a6aba3bdeef7d940d8e9e0e6d2c193595bc243241b77ff9e93620  libffi.tar.gz" > libffi.tar.gz.sha256
RUN sha256sum -c libffi.tar.gz.sha256
RUN tar -xf libffi.tar.gz
RUN mv libffi-${VERSION} /tmp/source


FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /