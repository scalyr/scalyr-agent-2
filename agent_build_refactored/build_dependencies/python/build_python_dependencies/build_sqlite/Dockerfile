#FROM download_source_base as download_tcl
#ARG TCL_VERSION_COMMIT
#RUN curl -L "https://github.com/tcltk/tcl/archive/${TCL_VERSION_COMMIT}.tar.gz" > tcl.tar.gz
#RUN tar xzf tcl.tar.gz
#RUN mv "tcl-${TCL_VERSION_COMMIT}" /tmp/source
#
#FROM download_source_base as download_sqlite
#WORKDIR sqlite
#ARG VERSION_COMMIT
#RUN curl -L "https://github.com/sqlite/sqlite/archive/${VERSION_COMMIT}.tar.gz" > sqlite.tar.gz
#RUN tar xzf sqlite.tar.gz
#RUN mv "sqlite-${VERSION_COMMIT}" /tmp/source

FROM prepare_build_base as build_tcl
#COPY --from=download_tcl /tmp/source /tmp/source
COPY --from=download_sources /tcl /tmp/source
WORKDIR /tmp/source/unix/build
ARG INSTALL_PREFIX
RUN ../configure --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM prepare_build_base as build_sqlite
COPY --from=build_tcl /tmp/root/. /
#COPY --from=download_sqlite /tmp/source /tmp/source
COPY --from=download_sources /sqlite /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" LDFLAGS="-L${INSTALL_PREFIX}/lib" ../configure \
    --prefix="${INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install



FROM scratch
COPY --from=build_sqlite /tmp/root/. /