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

set -e

# shellcheck disable=SC1090
source ~/.bashrc

AGENT_LIBS_PACKAGE_ROOT="${STEP_OUTPUT_PATH}/agent-libs"
AGENT_LIBS_WHEELS_PACKAGE_ROOT="${STEP_OUTPUT_PATH}/agent-libs-wheels"
mkdir -p "${AGENT_LIBS_WHEELS_PACKAGE_ROOT}/usr/share/scalyr-agent-2/agent-libs/wheels"
cp -a "${PREPARE_WHEELS_PY36}/wheels/." "${AGENT_LIBS_WHEELS_PACKAGE_ROOT}/usr/share/scalyr-agent-2/agent-libs/wheels"
cp -a "${PREPARE_WHEELS}/wheels/." "${AGENT_LIBS_WHEELS_PACKAGE_ROOT}/usr/share/scalyr-agent-2/agent-libs/wheels"
echo "${REQUIREMENTS}" > "${AGENT_LIBS_WHEELS_PACKAGE_ROOT}/usr/share/${SUBDIR_NAME}/agent-libs/requirements.txt"
echo "${PLATFORM_DEPENDENT_REQUIREMENTS}" > "${AGENT_LIBS_WHEELS_PACKAGE_ROOT}/usr/share/${SUBDIR_NAME}/agent-libs/binary-requirements.txt"


mkdir -p "${AGENT_LIBS_PACKAGE_ROOT}/usr/lib/${SUBDIR_NAME}/bin"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_libs/system_python/files/scalyr-agent-python3" "${AGENT_LIBS_PACKAGE_ROOT}/usr/lib/${SUBDIR_NAME}/bin/scalyr-agent-python3"

cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_libs/files/scalyr-agent-2-libs.py" "${AGENT_LIBS_PACKAGE_ROOT}/usr/lib/${SUBDIR_NAME}/bin/scalyr-agent-2-libs"

mkdir -p "${AGENT_LIBS_PACKAGE_ROOT}/etc/${SUBDIR_NAME}/agent-libs"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_libs/files/config/config.ini" "${AGENT_LIBS_PACKAGE_ROOT}/etc/${SUBDIR_NAME}/agent-libs/config.ini"
cp "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_libs/files/config/additional-requirements.txt" "${AGENT_LIBS_PACKAGE_ROOT}/etc/${SUBDIR_NAME}/agent-libs/additional-requirements.txt"