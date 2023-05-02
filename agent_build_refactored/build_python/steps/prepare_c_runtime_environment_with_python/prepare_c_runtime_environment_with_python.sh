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
#   FPM_VERSION: Version of the fpm tool.
#   PACKAGE_CLOUD_VERSION: Version of the package_cloud tools. used to manipulate Packagecloud packages.
#

set -e

cp -a "${BUILD_PYTHON_WITH_OPENSSL_1}/." /
cp -a "${BUILD_OPENSSL_1}/." /
cp -a "${BUILD_DEV_REQUIREMENTS}/root/." /

echo "${PYTHON_INSTALL_PREFIX}/lib" >> /etc/ld.so.conf.d/python3.conf
ldconfig

ln -s "${PYTHON_INSTALL_PREFIX}/bin/python3" /usr/bin/python3

# Copy pip cache
PIP_CACHE_DIR="$(python3 -m pip cache dir)"
mkdir -p "${PIP_CACHE_DIR}"

cp -a "${BUILD_DEV_REQUIREMENTS}/cache/." "${PIP_CACHE_DIR}"
