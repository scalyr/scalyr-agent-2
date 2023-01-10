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
# This script prepares base build environment for the ARM64 linux GLIBC binary packages, it expects to be run in
# Centos 7 to compile against lower GLIBS (2.17).

set -e

export DEBIAN_FRONTEND="noninteractive"
apt-get update
apt-get install -y software-properties-common

# Install new repository with newer compiler.
add-apt-repository ppa:ubuntu-toolchain-r/test
apt update
apt install -y gcc-9 make curl pkg-config cmake
update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 1
update-alternatives --install /usr/bin/cc cc /usr/bin/gcc-9 1

echo -e "/usr/local/lib\n/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf

apt clean
