FROM prepare_build_base as build_bzip
COPY --from=download_sources /bzip /tmp/source
WORKDIR /tmp/source
ARG INSTALL_PREFIX
RUN make install CFLAGS="-fPIC" PREFIX="/tmp/root${INSTALL_PREFIX}" -j "$(nproc)"


FROM prepare_build_base as build_ncurses
COPY --from=download_sources /ncurses /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_libedit
COPY --from=build_ncurses /tmp/root/. /
COPY --from=download_sources /libedit /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN ../configure \
  CFLAGS="-fPIC -I${INSTALL_PREFIX}/include -I${INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="-L${INSTALL_PREFIX}/lib -L${INSTALL_PREFIX}/lib64" \
  --prefix="${INSTALL_PREFIX}" \
  --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_libffi
COPY --from=download_sources /libffi /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_openssl_1
COPY --from=download_sources /openssl_1 /tmp/source
WORKDIR /tmp/source/build
ADD configure_openssl.sh configure_openssl.sh
ARG INSTALL_PREFIX
ARG ARCH
ARG LIBC
RUN ARCH="${ARCH}" LIBC="${LIBC}" MAJOR_VERSION="1" \
    bash configure_openssl.sh --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM prepare_build_base as build_openssl_3
COPY --from=download_sources /openssl_3 /tmp/source
WORKDIR /tmp/source/build
ADD configure_openssl.sh configure_openssl.sh
ARG INSTALL_PREFIX
ARG ARCH
ARG LIBC
RUN ARCH="${ARCH}" LIBC="${LIBC}" MAJOR_VERSION="1" \
    bash configure_openssl.sh --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM prepare_build_base as build_tcl
COPY --from=download_sources /tcl /tmp/source
WORKDIR /tmp/source/unix/build
ARG INSTALL_PREFIX
RUN ../configure --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM prepare_build_base as build_sqlite
COPY --from=build_tcl /tmp/root/. /
COPY --from=download_sources /sqlite /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" LDFLAGS="-L${INSTALL_PREFIX}/lib" ../configure \
    --prefix="${INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_util_linux
COPY --from=download_sources /util_linux /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix="${INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_xz
COPY --from=download_sources /xz /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN ../configure CFLAGS="-fPIC" \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared=no --disable-xzdec --disable-lzmadec
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM prepare_build_base as build_zlib
COPY --from=download_sources /zlib /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure  --static --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM scratch
COPY --from=build_bzip /tmp/root/. /bzip
COPY --from=build_libedit /tmp/root/. /libedit
COPY --from=build_libffi /tmp/root/. /libffi
COPY --from=build_ncurses /tmp/root/. /ncurses
COPY --from=build_openssl_1 /tmp/root/. /openssl_1
COPY --from=build_openssl_3 /tmp/root/. /openssl_3
COPY --from=build_sqlite /tmp/root/. /sqlite
COPY --from=build_util_linux /tmp/root/. /util_linux
COPY --from=build_xz /tmp/root/. /xz
COPY --from=build_zlib /tmp/root/. /zlib
