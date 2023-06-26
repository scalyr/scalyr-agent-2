FROM download_base as download
RUN gpg2 --import /tmp/public_keys/gnu-keyring.gpg
ARG VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xvf "ncurses.tar.gz"
RUN mv ncurses-${VERSION} /tmp/source

FROM prepare_build_base as build
COPY --from=download /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix=${INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM scratch
COPY --from=build /tmp/root/. /