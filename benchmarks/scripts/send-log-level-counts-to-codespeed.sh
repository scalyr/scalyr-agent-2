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

SCRIPT_DIR=$(readlink -f "$(dirname ${BASH_SOURCE[0]})")
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/common.sh"

SEND_VALUE_SCRPT_PATH=$(realpath "$(echo "${SCRIPT_DIR}/send_value_to_codespeed.py")")

AGENT_LOG_FILE_PATH="${HOME}/scalyr-agent-dev/log/agent.log"
AGENT_DEBUG_LOG_FILE_PATH="${HOME}/scalyr-agent-dev/log/agent_debug.log"

verify_mandatory_common_env_variables_are_set

if [ $# -lt 1 ]; then
    echo "Usage: ${0} <commit hash>"
    exit 2
fi

LINES_COUNT_INFO_LEVEL=$(cat ${AGENT_LOG_FILE_PATH}  | grep -a -P '^.*\s+INFO \[.*\].*$' | wc -l)
LINES_COUNT_WARNING_LEVEL=$(cat ${AGENT_LOG_FILE_PATH}  | grep -a -P '^.*\s+WARNING \[.*\].*$' | wc -l)
LINES_COUNT_ERROR_LEVEL=$(cat ${AGENT_LOG_FILE_PATH}  | grep -a -P '^.*\s+ERROR \[.*\].*$' | wc -l)
LINES_COUNT_DEBUG_LEVEL=$(cat ${AGENT_DEBUG_LOG_FILE_PATH}  | grep -a -P '^.*\s+DEBUG \[.*\].*$' | wc -l)

COMMON_COMMAND_LINE_ARGS="--codespeed-url=\"${CODESPEED_URL}\" \
    --codespeed-auth=\"${CODESPEED_AUTH}\" \
    --codespeed-project=\"${CODESPEED_PROJECT}\" \
    --codespeed-executable=\"${CODESPEED_EXECUTABLE}\" \
    --codespeed-environment=\"${CODESPEED_ENVIRONMENT}\" \
    --branch=\"${CODESPEED_BRANCH}\" \
    --commit-date=\"${COMMIT_DATE}\" \
    --commit-id=\"${COMMIT_HASH}\""

echo "Using COMMIT_DATE=${COMMIT_DATE} and COMMIT_ID=${COMMIT_HASH}"

eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_info" \
    --value=${LINES_COUNT_INFO_LEVEL}

eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_warning" \
    --value=${LINES_COUNT_WARNING_LEVEL}

eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_error" \
    --value=${LINES_COUNT_ERROR_LEVEL}

eval python ${SEND_VALUE_SCRPT_PATH} ${COMMON_COMMAND_LINE_ARGS} \
    --codespeed-benchmark="log_lines_debug" \
    --value=${LINES_COUNT_DEBUG_LEVEL}
