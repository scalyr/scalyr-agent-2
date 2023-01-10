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
# This script prepares toolset environment that will be used during packages build. For example, it installs
# the fpm command line tools which is used to create deb and rpm packages.
#
# It expects next environment variables:
#   BUILD_PYTHON: output path of the previous step that provides Python interpreter.
#   BUILD_AGENT_LIBS: output path of the previous step that provides dev libraries for the Python.
#   SUBDIR_NAME: Name of the sub-directory for Python interpreter and its libraries.
#   FPM_VERSION: Version of the fpm tool.
#   PACKAGE_CLOUD_VERSION: Version of the package_cloud tools. used to manipulate Packagecloud packages.
#

set -e

cp -a "${BUILD_PYTHON}/." /
cp -a "${BUILD_OPENSSL}/." /
cp -a "${BUILD_DEV_REQUIREMENTS}/root/." /
ldconfig

# shellcheck disable=SC1090
source ~/.bashrc

apt update
DEBIAN_FRONTEND=noninteractive apt install -y ruby ruby-dev rubygems build-essential rpm git reprepro createrepo-c gnupg2 patchelf binutils
gem install "fpm:${FPM_VERSION}" "package_cloud:${PACKAGECLOUD_VERSION}"




ln -s "/opt/${SUBDIR_NAME}/bin/python3" /usr/bin/python3

# Generate keypair to sign and verify test repos for packages.
gpg --batch --passphrase '' --quick-gen-key test default default

apt clean
