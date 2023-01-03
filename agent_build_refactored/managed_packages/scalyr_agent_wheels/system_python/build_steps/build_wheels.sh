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


WHEELS_DIR="${STEP_OUTPUT_PATH}/wheels"
mkdir -p "${WHEELS_DIR}"
COMMON_REQUIREMENTS_FILE="${WHEELS_DIR}/requirements.txt"
BINARY_REQUIREMENTS_FILE="${WHEELS_DIR}/binary-requirements.txt"

echo "${REQUIREMENTS_COMMON}" >> "${COMMON_REQUIREMENTS_FILE}"
echo "${REQUIREMENTS_COMMON_PLATFORM_DEPENDENT}" >> "${BINARY_REQUIREMENTS_FILE}"


TARBALLS_DIR="$STEP_OUTPUT_PATH/tarballs"
python3 -m pip download --no-binary=:all: \
  -d "${TARBALLS_DIR}" \
  -r "${COMMON_REQUIREMENTS_FILE}" \
  wheel setuptools setuptools_scm flit_core


rm "${TARBALLS_DIR}"/pycrypto-*
#rm "${TARBALLS_DIR}"/pycryptodome-*


# We patch the setup.py file of the 'pysnmp' package in order to remove the 'pycryptodome' package
# from its requirements, since it seems to be binary package, and here we only have "platform independent" packages.
mkdir /tmp/modified_packages
pushd /tmp/modified_packages

mkdir -p "$STEP_OUTPUT_PATH/pysnmp"



pushd "${SOURCE_ROOT}"
PYSNMP_TARBALL=$(find "${TARBALLS_DIR}" -name "pysnmp-*.*.*.tar.gz" -type f -maxdepth 1)
tar -xvf ${PYSNMP_TARBALL} -C "$STEP_OUTPUT_PATH/pysnmp" --strip-components=1
pushd "$STEP_OUTPUT_PATH/pysnmp"
patch -f "$STEP_OUTPUT_PATH/pysnmp/setup.py" "${SOURCE_ROOT}/agent_build_refactored/managed_packages/scalyr_agent_wheels/system_python/build_steps/pysnmp_setup.patch"
tar -czvf "${PYSNMP_TARBALL}" -C "$STEP_OUTPUT_PATH/pysnmp" .


if [ -n "${BUILD_SYSTEM_PYTHON_WHEELS_PY36}" ];then
  cp -a "${BUILD_SYSTEM_PYTHON_WHEELS_PY36}/wheels/." "${WHEELS_DIR}"
fi

python3 -m pip wheel \
  --no-index --find-links "${TARBALLS_DIR}" \
  --wheel-dir "${WHEELS_DIR}"  \
  -r "${COMMON_REQUIREMENTS_FILE}"