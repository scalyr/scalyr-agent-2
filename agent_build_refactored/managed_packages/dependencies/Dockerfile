ARG ARCH

FROM centos:6 as base_x86_64
ADD agent_build_refactored/managed_packages/dependencies/centos6/*.repo /etc/yum.repos.d/
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-9 perl-core
RUN echo -e "source /opt/rh/devtoolset-9/enable" >> /root/.bash_env
ENV BASH_ENV="/root/.bash_env"

FROM centos:7 as base_aarch64
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-9 perl-core
RUN echo -e "source /opt/rh/devtoolset-9/enable" >> /root/.bash_env
ENV BASH_ENV="/root/.bash_env"

FROM base_${ARCH} as base
SHELL ["/bin/bash", "-c"]


FROM ubuntu:22.04 as download_base
RUN DEBIAN_FRONTEND="noninteractive" \
    apt-get update && \
    apt-get install -y \
    gnupg2 \
    git \
    tar \
    curl

ADD agent_build_refactored/managed_packages/dependencies/public_keys /tmp/public_keys
WORKDIR /tmp/download


FROM download_base as download_bzip
RUN gpg2 --import /tmp/public_keys/bzip_keyring.gpg
ARG BZIP_VERSION
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz" > bzip2.tar.gz
RUN curl -L "https://sourceware.org/pub/bzip2/bzip2-${BZIP_VERSION}.tar.gz.sig" > bzip2.tar.gz.sig
RUN gpg2 --verify bzip2.tar.gz.sig bzip2.tar.gz
RUN tar -xf "bzip2.tar.gz"
RUN mv bzip2-${BZIP_VERSION} /tmp/source

FROM base as build_bzip
COPY --from=download_bzip /tmp/source /tmp/source
WORKDIR /tmp/source
ARG DEPENDENCIES_INSTALL_PREFIX
RUN make install CFLAGS="-fPIC" PREFIX="/tmp/root${DEPENDENCIES_INSTALL_PREFIX}" -j "$(nproc)"


FROM download_base as download_ncurses
RUN gpg2 --import /tmp/public_keys/gnu-keyring.gpg
ARG NCURSES_VERSION
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz" > ncurses.tar.gz
RUN curl -L "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-${NCURSES_VERSION}.tar.gz.sig" > ncurses.tar.gz.sig
RUN gpg2 --verify  ncurses.tar.gz.sig ncurses.tar.gz
RUN tar -xf "ncurses.tar.gz"
RUN mv ncurses-${NCURSES_VERSION} /tmp/source

FROM base as build_ncurses
COPY --from=download_ncurses /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix=${DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_libedit
ARG LIBEDIT_VERSION_COMMIT
RUN curl -L "https://salsa.debian.org/debian/libedit/-/archive/${LIBEDIT_VERSION_COMMIT}/libedit-${LIBEDIT_VERSION_COMMIT}.tar.gz" > libedit.tar.gz
RUN tar xf libedit.tar.gz
RUN mv "libedit-${LIBEDIT_VERSION_COMMIT}" /tmp/source

FROM base as build_libedit
COPY --from=build_ncurses /tmp/root/. /
COPY --from=download_libedit /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN ../configure \
  CFLAGS="-fPIC -I${DEPENDENCIES_INSTALL_PREFIX}/include -I${DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="-L${DEPENDENCIES_INSTALL_PREFIX}/lib -L${DEPENDENCIES_INSTALL_PREFIX}/lib64" \
  --prefix="${DEPENDENCIES_INSTALL_PREFIX}" \
  --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_libffi
ARG LIBFFI_VERSION
RUN curl -L -f "https://github.com/libffi/libffi/releases/download/v${LIBFFI_VERSION}/libffi-${LIBFFI_VERSION}.tar.gz" > libffi.tar.gz
# libffi does not provide any normal way of verifying its source, so every time when we update its
# version we have to manually calculate its checksum and hardcode it there.
RUN echo -n "540fb721619a6aba3bdeef7d940d8e9e0e6d2c193595bc243241b77ff9e93620  libffi.tar.gz" > libffi.tar.gz.sha256
RUN sha256sum -c libffi.tar.gz.sha256
RUN tar -xf libffi.tar.gz
RUN mv libffi-${LIBFFI_VERSION} /tmp/source

FROM base as build_libffi
COPY --from=download_libffi /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure \
    --prefix="${DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-multi-os-directory
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


# tcl is a dependency for the sqlite library.
FROM download_base as download_tcl
ARG TCL_VERSION_COMMIT
RUN curl -L "https://github.com/tcltk/tcl/archive/${TCL_VERSION_COMMIT}.tar.gz" > tcl.tar.gz
RUN tar xf tcl.tar.gz
RUN mv "tcl-${TCL_VERSION_COMMIT}" /tmp/source

FROM base as build_tcl
COPY --from=download_tcl /tmp/source /tmp/source
WORKDIR /tmp/source/unix/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN ../configure --prefix=${DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_sqlite
WORKDIR sqlite
ARG SQLITE_VERSION_COMMIT
RUN curl -L "https://github.com/sqlite/sqlite/archive/${SQLITE_VERSION_COMMIT}.tar.gz" > sqlite.tar.gz
RUN tar xf sqlite.tar.gz
RUN mv "sqlite-${SQLITE_VERSION_COMMIT}" /tmp/source

FROM base as build_sqlite
COPY --from=build_tcl /tmp/root/. /
COPY --from=download_sqlite /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN CFLAGS="-fPIC" LDFLAGS="-L${DEPENDENCIES_INSTALL_PREFIX}/lib" ../configure \
    --prefix="${DEPENDENCIES_INSTALL_PREFIX}"
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_util_linux
RUN gpg2 --import /tmp/public_keys/util_linux_public_key.gpg
ARG UTIL_LINUX_VERSION
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.gz" > util-linux.tar.gz
RUN curl -L "https://mirrors.edge.kernel.org/pub/linux/utils/util-linux/v${UTIL_LINUX_VERSION}/util-linux-${UTIL_LINUX_VERSION}.tar.sign" > util-linux.tar.sign
RUN gzip -dk util-linux.tar.gz
RUN gpg2 --verify util-linux.tar.sign util-linux.tar
RUN tar -xf util-linux.tar
RUN mv util-linux-${UTIL_LINUX_VERSION} /tmp/source

FROM base as build_util_linux
COPY --from=download_util_linux /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure --prefix="${DEPENDENCIES_INSTALL_PREFIX}" \
    --disable-all-programs  --enable-libuuid --enable-shared=no
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_xz
RUN gpg2 --import /tmp/public_keys/xz_public_key.gpg
ARG XZ_VERSION
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz" > xz.tar.gz
RUN curl -L "https://tukaani.org/xz/xz-${XZ_VERSION}.tar.gz.sig" > xz.tar.gz.sig
RUN gpg2 --verify xz.tar.gz.sig xz.tar.gz
RUN tar -xf xz.tar.gz
RUN mv xz-${XZ_VERSION} /tmp/source

FROM base as build_xz
COPY --from=download_xz /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN ../configure CFLAGS="-fPIC" \
    --prefix="${DEPENDENCIES_INSTALL_PREFIX}" \
    --enable-shared=no --disable-xzdec --disable-lzmadec
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install


FROM download_base as download_zlib
RUN gpg2 --import /tmp/public_keys/zlib_public_key.gpg
ARG ZLIB_VERSION
RUN curl -L -f "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz" > zlib.tar.gz
RUN curl -L -f "https://github.com/madler/zlib/releases/download/v${ZLIB_VERSION}/zlib-${ZLIB_VERSION}.tar.gz.asc" >  zlib.tar.gz.asc
RUN gpg2 --verify zlib.tar.gz.asc zlib.tar.gz
RUN tar -xf "zlib.tar.gz"
RUN mv zlib-${ZLIB_VERSION} /tmp/source

FROM base as build_zlib
COPY --from=download_zlib /tmp/source /tmp/source
WORKDIR /tmp/source/build
ARG DEPENDENCIES_INSTALL_PREFIX
RUN CFLAGS="-fPIC" ../configure  --static --prefix=${DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

FROM download_base as download_openssl_1
RUN gpg2 --import /tmp/public_keys/openssl_public_key.asc
ARG OPENSSL_1_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_1_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_1_VERSION} /tmp/source

FROM base as build_openssl_1
COPY --from=download_openssl_1 /tmp/source /tmp/source
WORKDIR /tmp/source/build
ADD agent_build_refactored/managed_packages/dependencies/configure_openssl.sh configure_openssl.sh
ARG DEPENDENCIES_INSTALL_PREFIX
ARG ARCH
RUN ARCH="${ARCH}" MAJOR_VERSION="1" \
    bash configure_openssl.sh --prefix=${DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM download_base as download_openssl_3
RUN gpg2 --import /tmp/public_keys/openssl_public_key.asc
ARG OPENSSL_3_VERSION
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz" > openssl.tar.gz
RUN curl -L "https://www.openssl.org/source/openssl-${OPENSSL_3_VERSION}.tar.gz.asc" > openssl.tar.gz.asc
RUN gpg2 --verify openssl.tar.gz.asc openssl.tar.gz
RUN tar -xf "openssl.tar.gz"
RUN mv openssl-${OPENSSL_3_VERSION} /tmp/source

FROM base as build_openssl_3
COPY --from=download_openssl_3 /tmp/source /tmp/source
WORKDIR /tmp/source/build
ADD agent_build_refactored/managed_packages/dependencies/configure_openssl.sh configure_openssl.sh
ARG DEPENDENCIES_INSTALL_PREFIX
ARG ARCH
RUN ARCH="${ARCH}" MAJOR_VERSION="3" \
    bash configure_openssl.sh --prefix=${DEPENDENCIES_INSTALL_PREFIX}
RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install_sw


FROM download_base as download_python
RUN gpg2 --import /tmp/public_keys/python_pub_key.gpg
ARG PYTHON_VERSION
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz" > python.tgz
RUN curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz.asc" > python.tgz.asc
RUN gpg --verify python.tgz.asc python.tgz
RUN tar -xf python.tgz
RUN mv Python-"${PYTHON_VERSION}" /tmp/source

FROM base as build_python_base
COPY --from=build_xz /tmp/root/. /
COPY --from=build_sqlite /tmp/root/. /
COPY --from=build_zlib /tmp/root/. /
COPY --from=build_bzip /tmp/root/. /
COPY --from=build_util_linux /tmp/root/. /
COPY --from=build_ncurses /tmp/root/. /
COPY --from=build_libedit /tmp/root/. /
COPY --from=build_libffi /tmp/root/. /
COPY --from=download_python /tmp/source /tmp/source

ARG DEPENDENCIES_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${DEPENDENCIES_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
WORKDIR /tmp/source/build

FROM build_python_base as build_python
COPY --from=build_openssl_3 /tmp/root/. /
ARG PYTHON_INSTALL_PREFIX
ARG DEPENDENCIES_INSTALL_PREFIX
RUN ../configure \
  CFLAGS="-I${DEPENDENCIES_INSTALL_PREFIX}/include -I${DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="${LDFLAGS} -L${DEPENDENCIES_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
    --with-openssl="${DEPENDENCIES_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${PYTHON_INSTALL_PREFIX}" \
	--with-ensurepip=no

RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

# Copy sqlite shared library because it's dfficult to make it compiled statically.
# TODO: But it would be good to create static.
COPY --from=build_sqlite /tmp/root /tmp/sqlite
RUN cp /tmp/sqlite${DEPENDENCIES_INSTALL_PREFIX}/lib/*.so* /tmp/root${PYTHON_INSTALL_PREFIX}/lib

# Remove cache files.
RUN find "/tmp/root${PYTHON_INSTALL_PREFIX}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# install built python to the current system
RUN cp -a /tmp/root/. /

RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m ensurepip
# Install upgraded pip version in the final python root.
RUN ${PYTHON_INSTALL_PREFIX}/bin/python3 -m pip install --upgrade pip setuptools --root /tmp/root

FROM build_python_base as build_python_with_openssl_1
COPY --from=build_openssl_1 /tmp/root/. /
ARG PYTHON_INSTALL_PREFIX
ARG DEPENDENCIES_INSTALL_PREFIX
RUN ../configure \
  CFLAGS="-I${DEPENDENCIES_INSTALL_PREFIX}/include -I${DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="${LDFLAGS} -L${DEPENDENCIES_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
    --with-openssl="${DEPENDENCIES_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${PYTHON_INSTALL_PREFIX}" \
	--with-ensurepip=no

RUN make -j "$(nproc)"
RUN make DESTDIR=/tmp/root install

RUN find "/tmp/root${PYTHON_INSTALL_PREFIX}" -name "__pycache__" -type d -prune -exec rm -r {} \;


FROM download_base as download_rust
ARG RUST_VERSION
ARG RUST_PLATFORM
ADD agent_build_refactored/managed_packages/dependencies/public_keys/rust-key.gpg.ascii /tmp/public_keys/rust-key.gpg.ascii
RUN gpg2 --import /tmp/public_keys/rust-key.gpg.ascii
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
RUN curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz.asc" > rust.tar.gz.asc
RUN gpg --verify rust.tar.gz.asc rust.tar.gz
RUN tar -xzf rust.tar.gz
RUN mv rust-${RUST_VERSION}-${RUST_PLATFORM} /tmp/rust


FROM base as base_with_python
ARG PYTHON_INSTALL_PREFIX
ARG DEPENDENCIES_INSTALL_PREFIX
ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${DEPENDENCIES_INSTALL_PREFIX}/lib"
ENV PATH="${PYTHON_INSTALL_PREFIX}/bin:/root/.cargo/bin:${PATH}"
ENV PKG_CONFIG_PATH="${DEPENDENCIES_INSTALL_PREFIX}/lib64/pkgconfig:${DEPENDENCIES_INSTALL_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH}"
COPY --from=build_libffi /tmp/root/. /
COPY --from=build_zlib /tmp/root/. /
COPY --from=build_openssl_3 /tmp/root/. /
COPY --from=build_python /tmp/root/. /

FROM base_with_python as build_dev_requirements
COPY --from=download_rust /tmp/rust /tmp/rust
WORKDIR /tmp/rust
RUN ./install.sh

ADD dev-requirements-new.txt /tmp/requirements.txt
RUN python3 -m pip wheel \
    -r /tmp/requirements.txt \
    --wheel-dir /tmp/wheels

RUN python3 -m pip install \
    -r /tmp/requirements.txt \
    --no-index \
    --find-links /tmp/wheels \
    --no-warn-script-location \
    --root-user-action=ignore \
    --root /tmp/root


FROM base_with_python as build_venv
ARG REQUIREMENTS_FILE_CONTENT
RUN echo "${REQUIREMENTS_FILE_CONTENT}" > /tmp/requirements.txt
ARG SUBDIR_NAME="scalyr-agent-2"
ARG PYTHON_INSTALL_PREFIX
ARG VENV_DIR="/var/opt/${SUBDIR_NAME}/venv"
RUN python3 -m venv "${VENV_DIR}"

COPY --from=build_dev_requirements /tmp/wheels /tmp/wheels

RUN "${VENV_DIR}/bin/python3" -m pip install \
    --no-index \
    --find-links /tmp/wheels \
    --no-warn-script-location \
    --root-user-action=ignore \
    -r /tmp/requirements.txt

# Remove cache files.
RUN find "${VENV_DIR}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# Copy result venv to result output.
RUN cp -a "${VENV_DIR}" /tmp/venv

FROM base_with_python as installed_python_with_requirements
COPY --from=build_dev_requirements /tmp/root/. /

FROM installed_python_with_requirements as build_portable_pytest_runner
ARG PORTABLE_RUNNER_NAME

WORKDIR /tmp/source

ADD agent_build_refactored/managed_packages/dependencies/pytest_runer_main.py pytest_runer_main.py

RUN python3 -m PyInstaller \
    --onefile \
    --name ${PORTABLE_RUNNER_NAME} \
    pytest_runer_main.py


FROM scratch
COPY --from=build_python /tmp/root /python
COPY --from=build_python_with_openssl_1 /tmp/root /python_with_openssl_1
COPY --from=build_openssl_1 /tmp/root /openssl_1
COPY --from=build_openssl_3 /tmp/root /openssl_3
COPY --from=build_venv /tmp/venv /venv
ARG PORTABLE_RUNNER_NAME
COPY --from=build_portable_pytest_runner /tmp/source/dist/${PORTABLE_RUNNER_NAME} /${PORTABLE_RUNNER_NAME}


