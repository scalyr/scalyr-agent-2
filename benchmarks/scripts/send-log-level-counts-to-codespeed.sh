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

# Script which sends line count for log messages for a particular log level to CodeSpeed
set -e

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/common.sh"

SEND_VALUE_SCRPT_PATH=$(realpath "${SCRIPT_DIR}/send_value_to_codespeed.py")

AGENT_LOG_FILE_PATH="${HOME}/scalyr-agent-dev/log/agent.log"
AGENT_DEBUG_LOG_FILE_PATH="${HOME}/scalyr-agent-dev/log/agent_debug.log"

verify_mandatory_common_env_variables_are_set

if [ $# -lt 1 ]; then
    echo "Usage: ${0} <commit hash>"
    exit 2
fi

LINES_COUNT_INFO_LEVEL=$(grep -c -a -P '^.*\s+INFO \[.*\].*$' "${AGENT_LOG_FILE_PATH}")
LINES_COUNT_WARNING_LEVEL=$(grep -c -a -P '^.*\s+WARNING \[.*\].*$' "${AGENT_LOG_FILE_PATH}")
LINES_COUNT_ERROR_LEVEL=$(grep -c -a -P '^.*\s+ERROR \[.*\].*$' "${AGENT_LOG_FILE_PATH}")
LINES_COUNT_DEBUG_LEVEL=$(grep -c -a -P '^.*\s+DEBUG \[.*\].*$' "${AGENT_DEBUG_LOG_FILE_PATH}")

COMMON_COMMAND_LINE_ARGS="--codespeed-url=\"${CODESPEED_URL}\" \
    --codespeed-auth=\"${CODESPEED_AUTH}\" \
    --codespeed-project=\"${CODESPEED_PROJECT}\" \
    --codespeed-executable=\"${CODESPEED_EXECUTABLE}\" \
    --codespeed-environment=\"${CODESPEED_ENVIRONMENT}\" \
    --branch=\"${CODESPEED_BRANCH}\" \
    --commit-date=\"${COMMIT_DATE}\" \
    --commit-id=\"${COMMIT_HASH}\""

echo "Using COMMIT_DATE=${COMMIT_DATE}, COMMIT_ID=${COMMIT_HASH}, BRANCH=${BRANCH}"

# shellcheck disable=SC2086
eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_info" \
    --value="${LINES_COUNT_INFO_LEVEL}"

# shellcheck disable=SC2086
eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_warning" \
    --value="${LINES_COUNT_WARNING_LEVEL}"

# shellcheck disable=SC2086
eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_error" \
    --value="${LINES_COUNT_ERROR_LEVEL}"

# shellcheck disable=SC2086
eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_debug" \
    --value="${LINES_COUNT_DEBUG_LEVEL}"
