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


#cp -a "${BUILD_PYTHON}/python/." /
##cp -a "${BUILD_AGENT_DEV_REQUIREMENTS}/." /

REQUIREMENTS_FILE="/tmp/requirements.txt"


echo "${REQUIREMENTS_COMMON}" >> "${REQUIREMENTS_FILE}"
echo "${REQUIREMENTS_COMMON_PLATFORM_DEPENDENT}" >> "${REQUIREMENTS_FILE}"



WHEELS_DIR="${STEP_OUTPUT_PATH}/wheels"

/usr/lib/scalyr-agent-2/python3/bin/python3 -m pip wheel \
  --no-index \
  --find-links "${BUILD_AGENT_DEV_REQUIREMENTS}" \
  --wheel-dir "${WHEELS_DIR}"  \
  -r "${REQUIREMENTS_FILE}"