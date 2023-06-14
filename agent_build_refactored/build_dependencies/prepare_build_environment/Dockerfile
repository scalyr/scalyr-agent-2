ARG TARGET
ARG TARGET_LIBC
ARG TARGET_ROOT_PATH="/opt/x-tools/${TARGET}"


FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-gnu_x86_64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as  toolchain_x86_64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/aarch64-unknown-linux-gnu_aarch64-unknown-linux-gnu:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_aarch64-unknown-linux-gnu
FROM ghcr.io/arthurkamalov/toolchains/dev/armv7-unknown-linux-gnueabihf_armv7-unknown-linux-gnueabihf:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_armv7-unknown-linux-gnueabihf

FROM ghcr.io/arthurkamalov/toolchains/dev/x86_64-unknown-linux-musl_x86_64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_x86_64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/aarch64-unknown-linux-musl_aarch64-unknown-linux-musl:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_aarch64-unknown-linux-musl
FROM ghcr.io/arthurkamalov/toolchains/dev/armv7-unknown-linux-musleabihf_armv7-unknown-linux-musleabihf:18cbb43ba750d77ee233c83322991499b6a91895 as toolchain_armv7-unknown-linux-musleabihf


FROM toolchain_${TARGET} as toolchain
ARG TARGET_ROOT_PATH
RUN mkdir -p "/tmp/root${TARGET_ROOT_PATH}"
RUN cp -a "${TARGET_ROOT_PATH}/." "/tmp/root${TARGET_ROOT_PATH}"

FROM ubuntu:jammy-20230522 as blank_base_gnu

FROM alpine:3.18.0 as blank_base_musl

FROM blank_base_gnu as build_base_gnu
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt update && apt install -y  \
    curl tar make git automake autoconf pkg-config gnupg2

FROM blank_base_musl as build_base_musl
RUN apk add \
    curl tar make git automake autoconf pkgconfig gnupg bash libstdc++ musl-dev

SHELL ["/usr/bin/env", "bash", "-c"]

FROM build_base_${TARGET_LIBC}
ARG TARGET
ARG TARGET_ROOT_PATH
ARG COMMON_DEPENDENCIES_INSTALL_PREFIX
ENV TARGET="${TARGET}"
ENV PATH="${TARGET_ROOT_PATH}/bin:${PATH}"
ENV COMMON_DEPENDENCIES_INSTALL_PREFIX="${COMMON_DEPENDENCIES_INSTALL_PREFIX}"
COPY --from=toolchain ${TARGET_ROOT_PATH} "${TARGET_ROOT_PATH}"
ADD create_toolchain_symlinks.sh create_toolchain_symlinks.sh
RUN bash create_toolchain_symlinks.sh
RUN rm create_toolchain_symlinks.sh
WORKDIR /tmp/build