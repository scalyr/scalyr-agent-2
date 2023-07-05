FROM ubuntu:22.04 as base
RUN apt-get update && apt install -y \
    gnupg2 \
    git \
    tar \
    curl
ADD public_keys /tmp/public_keys
WORKDIR /tmp/download

FROM base as bzip
RUN gpg2 --import /tmp/public_keys/bzip_keyring.gpg
ARG BZIP_VERSION
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz" > bzip2.tar.gz
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz.sig" > bzip2.tar.gz.sig
RUN gpg2 --verify bzip2.tar.gz.sig bzip2.tar.gz
RUN tar -xf "bzip2.tar.gz"
RUN mv bzip2-${BZIP_VERSION} /tmp/source

FROM base as libedit
ARG LIBEDIT_VERSION_COMMIT
RUN curl -L "https://salsa.debian.org/debian/libedit/-/archive/${LIBEDIT_VERSION_COMMIT}/libedit-${LIBEDIT_VERSION_COMMIT}.tar.gz" > libedit.tar.gz
RUN tar xf libedit.tar.gz
RUN mv "libedit-${LIBEDIT_VERSION_COMMIT}" /tmp/source

FROM base as libffi
ARG LIBFFI_VERSION
RUN curl -L -f "https://github.com/libffi/libffi/releases/download/v${LIBFFI_VERSION}/libffi-${LIBFFI_VERSION}.tar.gz" > libffi.tar.gz
# libffi does not provide any normal way of verifying its source, so every time when we update its
# version we have to manually calculate its checksum and hardcode it there.
RUN echo -n "540fb721619a6aba3bdeef7d940d8e9e0e6d2c193595bc243241b77ff9e93620  libffi.tar.gz" > libffi.tar.gz.sha256
RUN sha256sum -c libffi.tar.gz.sha256
RUN tar -xf libffi.tar.gz
RUN mv libffi-${LIBFFI_VERSION} /tmp/source

FROM base as ncurses
RUN gpg2 --import /tmp/public_keys/gnu-keyring.gpg
ARG NCURSES_VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xf "ncurses.tar.gz"
RUN mv ncurses-${NCURSES_VERSION} /tmp/source

FROM base as openssl_1
RUN gpg2 --import /tmp/public_keys/openssl_public_key.asc
ARG OPENSSL_1_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_1_VERSION} /tmp/source

FROM base as openssl_3
RUN gpg2 --import /tmp/public_keys/openssl_public_key.asc
ARG OPENSSL_3_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_3_VERSION} /tmp/source

# tcl is a dependency for the sqlite library.
FROM base as tcl
ARG TCL_VERSION_COMMIT
RUN curl -L "https://github.com/tcltk/tcl/archive/${TCL_VERSION_COMMIT}.tar.gz" > tcl.tar.gz
RUN tar xf tcl.tar.gz
RUN mv "tcl-${TCL_VERSION_COMMIT}" /tmp/source

FROM base as sqlite
WORKDIR sqlite
ARG SQLITE_VERSION_COMMIT
RUN curl -L "https://github.com/sqlite/sqlite/archive/${SQLITE_VERSION_COMMIT}.tar.gz" > sqlite.tar.gz
RUN tar xf sqlite.tar.gz
RUN mv "sqlite-${SQLITE_VERSION_COMMIT}" /tmp/source

FROM base as util_linux
RUN gpg2 --import /tmp/public_keys/util_linux_public_key.gpg
ARG UTIL_LINUX_VERSION
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.gz" > util-linux.tar.gz
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.sign" > util-linux.tar.sign
RUN gzip -dk util-linux.tar.gz
RUN gpg2 --verify util-linux.tar.sign util-linux.tar
RUN tar -xf util-linux.tar
RUN mv util-linux-${UTIL_LINUX_VERSION} /tmp/source

FROM base as xz
RUN gpg2 --import /tmp/public_keys/xz_public_key.gpg
ARG XZ_VERSION
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz" > xz.tar.gz
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz.sig" > xz.tar.gz.sig
RUN gpg2 --verify xz.tar.gz.sig xz.tar.gz
RUN tar -xf xz.tar.gz
RUN mv xz-${XZ_VERSION} /tmp/source

FROM base as zlib
RUN gpg2 --import /tmp/public_keys/zlib_public_key.gpg
ARG ZLIB_VERSION
RUN curl -L -f "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L -f "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
RUN mv zlib-${ZLIB_VERSION} /tmp/source

FROM base as python
RUN gpg2 --import /tmp/public_keys/python_pub_key.gpg
ARG PYTHON_VERSION
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz
RUN mv Python-"${PYTHON_VERSION}" /tmp/source

FROM scratch
COPY --from=bzip /tmp/source /bzip
COPY --from=libedit /tmp/source /libedit
COPY --from=libffi /tmp/source /libffi
COPY --from=ncurses /tmp/source /ncurses
COPY --from=openssl_1 /tmp/source /openssl_1
COPY --from=openssl_3 /tmp/source /openssl_3
COPY --from=tcl /tmp/source /tcl
COPY --from=sqlite /tmp/source /sqlite
COPY --from=util_linux /tmp/source /util_linux
COPY --from=xz /tmp/source /xz
COPY --from=zlib /tmp/source /zlib
COPY --from=python /tmp/source /python