#!/usr/bin/env bash
# Copyright 2014-2020 Scalyr Inc.
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

set -e

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/common.sh"

CAPTURE_METRICS_SCRIPT_PATH=$(realpath "${SCRIPT_DIR}/send_usage_data_to_codespeed.py")

verify_mandatory_common_env_variables_are_set

if [ $# -lt 1 ]; then
    echo "Usage: ${0} <commit hash>"
    exit 2
fi

python "${CAPTURE_METRICS_SCRIPT_PATH}" \
  --agent-data-path="${AGENT_DATA_PATH}" \
  --capture-time="${CAPTURE_TIME}" \
  --capture-interval="${CAPTURE_INTERVAL}" \
  --codespeed-url="${CODESPEED_URL}" \
  --codespeed-auth="${CODESPEED_AUTH}" \
  --codespeed-project="${CODESPEED_PROJECT}" \
  --codespeed-executable="${CODESPEED_EXECUTABLE}" \
  --codespeed-environment="${CODESPEED_ENVIRONMENT}" \
  --branch="${CODESPEED_BRANCH}" \
  --commit-date="${COMMIT_DATE}" \
  --commit-id="${COMMIT_SHA1}" \
  --debug \
  ${ADDITIONAL_CAPTURE_SCRIPT_FLAGS} \
