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
# This script downloads and builds Python libraries that are required by the agent.
# it produces two directories:
#     - dev_libs - root for all project requirement libraries. Mainly supposed to be used in various build and testing
#         tools and images.
#     - agent_libs: root for the agent_libs package. It contains only libraries that are required by the agent.

set -e

# shellcheck disable=SC1090
source ~/.bashrc

PACKAGE_ROOT="${STEP_OUTPUT_PATH}/root"
mkdir -p "${PACKAGE_ROOT}"

VENV_DIR="${PACKAGE_ROOT}/opt/${SUBDIR_NAME}/venv"
mkdir -p "${VENV_DIR}"
cp -a "${BUILD_AGENT_LIBS}/venv/." "${VENV_DIR}"


mkdir -p "${PACKAGE_ROOT}/opt/${SUBDIR_NAME}/etc"
echo "${REQUIREMENTS}" > "${PACKAGE_ROOT}/opt/${SUBDIR_NAME}/etc/core-requirements.txt"

mkdir -p "${PACKAGE_ROOT}/etc/scalyr-agent-2"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/files/config/additional-requirements.txt" "${PACKAGE_ROOT}/etc/scalyr-agent-2"

mkdir -p "${PACKAGE_ROOT}/opt/${SUBDIR_NAME}/bin"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/files/recreate_venv" "${PACKAGE_ROOT}/opt/${SUBDIR_NAME}/bin"

PACKAGE_SCRIPTLETS_DIR="${STEP_OUTPUT_PATH}/scriptlets"
mkdir -p "${PACKAGE_SCRIPTLETS_DIR}"

cp "agent_build_refactored/managed_packages/install-scriptlets/scalyr-agent-libs/postinstall.sh" "${PACKAGE_SCRIPTLETS_DIR}"

