#!/usr/bin/env bash
# Copyright 2014-2022 Scalyr Inc.
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

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script installs all requirements of the Agent's project, including development and testing requirements.
#

set -e

# shellcheck disable=SC1090
source ~/.bashrc

# Copy python interpreter, which is built by the previous step.
cp -a "${BUILD_PYTHON}/." /
cp -a "${BUILD_OPENSSL}/." /
tar -xzf "${BUILD_PYTHON_DEPENDENCIES}/common.tar.gz" -C /
ldconfig

# First install Rust, in order to be able to build some of required libraries.
cd ~
export PATH="/usr/local/bin:/root/.cargo/bin:${PATH}"
export PKG_CONFIG_PATH="/usr/local/lib64/pkgconfig:/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH}"

mkdir -p /tmp/rust
pushd /tmp/rust
curl --tlsv1.2 "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-${RUST_PLATFORM}.tar.gz" > rust.tar.gz
tar -xzf rust.tar.gz

pushd "rust-${RUST_VERSION}-${RUST_PLATFORM}"

./install.sh

popd
popd

cargo install cargo-update -v

export LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"
# Install all requirements and save them and their cache.
"${PYTHON_INSTALL_PREFIX}/bin/python3" -m pip install \
  --root "${STEP_OUTPUT_PATH}/root" \
  --cache-dir "${STEP_OUTPUT_PATH}/cache" \
  -r "${SOURCE_ROOT}/dev-requirements-new.txt"