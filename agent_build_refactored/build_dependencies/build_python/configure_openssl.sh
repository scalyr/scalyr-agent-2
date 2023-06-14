# Examples for openssl configure options are peeked from:
#   Ubuntu(GLIBC):
#       OpenSSL 3: https://launchpad.net/ubuntu/+source/openssl/3.0.8-1ubuntu2
#       OpenSSL 1: https://launchpad.net/ubuntu/+source/openssl/1.1.1f-1ubuntu2.18
#   Alpine(Musl):
#       OpenSSL 3:
#       OpenSSL 1:


OPENSSL_MAJOR_VERSION="${1}"
shift

UBUNTU_OPENSSL_3_COMMON_ARGS="no-idea no-mdc2 no-rc5 no-zlib no-ssl3 enable-unit-test no-ssl3-method enable-rfc3779 enable-cms no-capieng no-rdrand"
UBUNTU_OPENSSL_1_COMMON_ARGS="no-idea no-mdc2 no-rc5 no-zlib no-ssl3 enable-unit-test no-ssl3-method enable-rfc3779 enable-cms"

ALPINE_OPENSSL_3_COMMON_ARGS="enable-ktls no-zlib no-async no-comp no-idea no-mdc2 no-rc5 no-ec2m no-sm2 no-sm4 no-ssl3 no-seed no-weak-ssl-ciphers"
ALPINE_OPENSSL_1_COMMON_ARGS="no-zlib no-async no-comp no-idea no-mdc2 no-rc5 no-ec2m no-sm2 no-sm4 no-ssl2 no-ssl3 no-seed no-weak-ssl-ciphers"
ALPINE_OPENSSL_3_COMMON_LDFLAGS="-Wa,--noexecstack"
ALPINE_OPENSSL_1_COMMON_LDFLAGS="-Wa,--noexecstack"

OPENSSL_3_LDFLAGS=
OPENSSL_1_LDFLAGS=


case "$TARGET" in
  x86_64-*-*-gnu*)
    OPENSSL_TARGET="linux-x86_64"
    OPENSSL_3_ARGS="${UBUNTU_OPENSSL_3_COMMON_ARGS} enable-ec_nistp_64_gcc_128"
    OPENSSL_1_ARGS="${UBUNTU_OPENSSL_1_COMMON_ARGS} enable-ec_nistp_64_gcc_128"
    ;;
  *aarch64-*-*-gnu*)
    OPENSSL_TARGET="linux-aarch64"
    OPENSSL_3_ARGS="${UBUNTU_OPENSSL_3_COMMON_ARGS}"
    OPENSSL_1_ARGS="${UBUNTU_OPENSSL_1_COMMON_ARGS}"
    ;;
  *armv7-*-*-gnu*)
    OPENSSL_TARGET="linux-armv4"
    OPENSSL_3_ARGS="${UBUNTU_OPENSSL_3_COMMON_ARGS}"
    OPENSSL_1_ARGS="${UBUNTU_OPENSSL_1_COMMON_ARGS}"
    ;;
  x86_64-*-*-musl*)
    OPENSSL_TARGET="linux-x86_64"
    OPENSSL_3_ARGS="${ALPINE_OPENSSL_3_COMMON_ARGS} enable-ec_nistp_64_gcc_128"
    OPENSSL_1_ARGS="${ALPINE_OPENSSL_1_COMMON_ARGS}"
    OPENSSL_3_LDFLAGS="${ALPINE_OPENSSL_3_COMMON_LDFLAGS}"
    OPENSSL_1_LDFLAGS="${ALPINE_OPENSSL_1_COMMON_LDFLAGS}"
    ;;
  *aarch64-*-*-musl*)
    OPENSSL_TARGET="linux-aarch64"
    OPENSSL_3_ARGS="${ALPINE_OPENSSL_3_COMMON_ARGS}"
    OPENSSL_1_ARGS="${ALPINE_OPENSSL_1_COMMON_ARGS}"
    OPENSSL_3_LDFLAGS="${ALPINE_OPENSSL_3_COMMON_LDFLAGS}"
    OPENSSL_1_LDFLAGS="${ALPINE_OPENSSL_1_COMMON_LDFLAGS}"
    ;;
  *armv7-*-*-musl*)
    OPENSSL_TARGET="linux-armv4"
    OPENSSL_3_ARGS="${ALPINE_OPENSSL_3_COMMON_ARGS}"
    OPENSSL_3_LDFLAGS="${ALPINE_OPENSSL_3_COMMON_LDFLAGS}"
    OPENSSL_1_ARGS="${ALPINE_OPENSSL_1_COMMON_ARGS}"
    OPENSSL_1_LDFLAGS="${ALPINE_OPENSSL_1_COMMON_LDFLAGS}"
    ;;
  *)
    echo -e "Can not determine distro by TARGET: '${TARGET}'"
    exit 1
  ;;
esac


if [ "${OPENSSL_MAJOR_VERSION}" = "3" ]; then
  ADDITIONAL_ARGS="${OPENSSL_3_ARGS}"
  ADDITIONAL_LDFLAGS="${OPENSSL_3_LDFLAGS}"
elif [ "${OPENSSL_MAJOR_VERSION}" = "1" ]; then
  ADDITIONAL_ARGS="${OPENSSL_1_ARGS}"
  ADDITIONAL_LDFLAGS="${OPENSSL_1_LDFLAGS}"
else
  echo -e "Unknown major version of OpenSSL: ${OPENSSL_MAJOR_VERSION}"
  exit 1
fi

pwd

../Configure "${OPENSSL_TARGET}" shared \
    ${ADDITIONAL_ARGS} \
    LDFLAGS="${LDFLAGS} ${ADDITIONAL_LDFLAGS}" \
    --libdir=lib \
    "$@"