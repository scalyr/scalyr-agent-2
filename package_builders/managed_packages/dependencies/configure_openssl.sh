#!/usr/bin/env bash
# Copyright 2014-2023 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Examples for openssl configure options are peeked from:
#   Ubuntu(GLIBC):
#       OpenSSL 3: https://launchpad.net/ubuntu/+source/openssl/3.0.8-1ubuntu2
#       OpenSSL 1: https://launchpad.net/ubuntu/+source/openssl/1.1.1f-1ubuntu2.18

UBUNTU_OPENSSL_3_COMMON_ARGS="no-idea no-mdc2 no-rc5 no-zlib no-ssl3 enable-unit-test no-ssl3-method enable-rfc3779 enable-cms no-capieng no-rdrand"
UBUNTU_OPENSSL_1_COMMON_ARGS="no-idea no-mdc2 no-rc5 no-zlib no-ssl3 enable-unit-test no-ssl3-method enable-rfc3779 enable-cms"


case "$ARCH" in
  x86_64)
    OPENSSL_TARGET="linux-x86_64"
    OPENSSL_3_ARGS="${UBUNTU_OPENSSL_3_COMMON_ARGS} enable-ec_nistp_64_gcc_128"
    OPENSSL_1_ARGS="${UBUNTU_OPENSSL_1_COMMON_ARGS} enable-ec_nistp_64_gcc_128"
    ;;
  aarch64)
    OPENSSL_TARGET="linux-aarch64"
    OPENSSL_3_ARGS="${UBUNTU_OPENSSL_3_COMMON_ARGS}"
    OPENSSL_1_ARGS="${UBUNTU_OPENSSL_1_COMMON_ARGS}"
    ;;
  *)
    echo -e "Can not determine target architecture for GNU by ARCH: '${ARCH}'"
    exit 1
    ;;
esac



if [ "${MAJOR_VERSION}" = "3" ]; then
  ADDITIONAL_ARGS="${OPENSSL_3_ARGS}"
elif [ "${MAJOR_VERSION}" = "1" ]; then
  ADDITIONAL_ARGS="${OPENSSL_1_ARGS}"
else
  echo -e "Unknown major version of OpenSSL: ${MAJOR_VERSION}"
  exit 1
fi

pwd

# shellcheck disable=SC2086
../Configure "${OPENSSL_TARGET}" shared ${ADDITIONAL_ARGS} --libdir=lib "$@"