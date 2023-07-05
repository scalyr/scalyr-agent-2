#FROM download_source_base as download
#ARG VERSION_COMMIT
#RUN curl -L "https://salsa.debian.org/debian/libedit/-/archive/${VERSION_COMMIT}/libedit-${VERSION_COMMIT}.tar.gz" > libedit.tar.gz
#RUN tar xzf libedit.tar.gz
#RUN mv "libedit-${VERSION_COMMIT}" /tmp/source

FROM prepare_build_base as build
COPY --from=build_ncurses / /
#COPY --from=download /tmp/libedit.tar /tmp/libedit.tar
#COPY --from=download /tmp/source /tmp/source
COPY --from=download_sources /libedit /tmp/source
#RUN mkdir -p /tmp/source
#RUN tar xzf /tmp/libedit.tar -C /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN ../configure \
  CFLAGS="-fPIC -I${INSTALL_PREFIX}/include -I${INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="-L${INSTALL_PREFIX}/lib -L${INSTALL_PREFIX}/lib64" \
  --prefix="${INSTALL_PREFIX}" \
  --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /