FROM download_base as download_tcl
RUN git clone "https://github.com/tcltk/tcl.git"
ARG TCL_VERSION_COMMIT
WORKDIR tcl
RUN git checkout "${TCL_VERSION_COMMIT}"
RUN rm -r .git
WORKDIR ..
RUN mv tcl /tmp/source

FROM download_base as download_sqlite
RUN git clone "https://github.com/sqlite/sqlite.git"
WORKDIR sqlite
ARG VERSION
RUN git checkout "${VERSION}"
RUN rm -r .git
WORKDIR ..
RUN mv sqlite /tmp/source

FROM prepare_build_base as build_tcl
COPY --from=download_tcl /tmp/source /tmp/source
WORKDIR /tmp/source/unix/build
ARG INSTALL_PREFIX
RUN ../configure --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM prepare_build_base as build_sqlite
COPY --from=build_tcl /tmp/root/. /
COPY --from=download_sqlite /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" LDFLAGS="-L${INSTALL_PREFIX}/lib" ../configure \
    --prefix="${INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install



FROM scratch
COPY --from=build_sqlite /tmp/root/. /