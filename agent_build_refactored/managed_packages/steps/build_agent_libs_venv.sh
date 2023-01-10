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
# This script creates venv with all libraries that are required by the Agent.

set -e

# shellcheck disable=SC1090
source ~/.bashrc

# Copy python interpreter, which is built by the previous step.

cp -a "${BUILD_PYTHON}/." /
cp -a "${BUILD_OPENSSL}/." /
cp -a "${BUILD_DEV_REQUIREMENTS}/root/." /
cp -a "${BUILD_DEV_REQUIREMENTS}/cache" /tmp/pip_cache
ldconfig

# Prepare requirements file.
REQUIREMENTS_FILE=/tmp/requirements.txt
echo "${REQUIREMENTS}" > "${REQUIREMENTS_FILE}"


# Create venv.
VENV_DIR="/var/opt/${SUBDIR_NAME}/venv"
"/opt/${SUBDIR_NAME}/bin/python3" -m venv "${VENV_DIR}"

# Install requirements to venv.
"${VENV_DIR}/bin/python3" -m pip install  -v \
  --cache-dir /tmp/pip_cache \
  -r "${REQUIREMENTS_FILE}"

# Copy result venv to result output.
cp -a "${VENV_DIR}" "${STEP_OUTPUT_PATH}"