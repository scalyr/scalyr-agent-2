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

#
# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script builds from source the OpenSSL 3+ library.
#


set -e


mkdir /tmp/build-openssl_3
pushd /tmp/build-openssl_3
tar -xf "${DOWNLOAD_BUILD_DEPENDENCIES}/openssl_3/openssl.tar.gz"
pushd "openssl-${OPENSSL_VERSION}"
./config
make -j "$(nproc)"
make DESTDIR="${STEP_OUTPUT_PATH}" install_sw
popd
popd


if [ "${DISTRO_NAME}" = "centos:6" ]; then
  mv "${STEP_OUTPUT_PATH}/usr/local/lib64" "${STEP_OUTPUT_PATH}/usr/local/lib"
fi

mkdir -p "${STEP_OUTPUT_PATH}/etc/ld.so.conf.d"
echo "/usr/local/lib" >> "${STEP_OUTPUT_PATH}/etc/ld.so.conf.d/local.conf"
echo "/usr/local/lib64" >> "${STEP_OUTPUT_PATH}/etc/ld.so.conf.d/local.conf"