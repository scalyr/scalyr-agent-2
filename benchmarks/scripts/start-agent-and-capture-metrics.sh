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

# Script which starts the agent in the foreground with the provided configuration file, runs it for
# X minutes, captures relevant agent process level metrics and submits them to CodeSpeed.

# NOTE: This script intentionally runs the agent directly inside the main Circle CI job command
# container to avoid additional container overhead.
# Eventually we will want to run those benchmarks / metrics captures on dedicated hosts to ensure
# consistent behavior and performance across runs.
# In the mean time, if the performance on Circle CI is too unpredictable, we will need to do multiple
# run and use a computed percentile value or similar.

# Every command failure (aka non zero exit) in the script should be treated as a fatal error
set -e

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/common.sh"

verify_mandatory_common_env_variables_are_set

if [ -z "${AGENT_CONFIG_FILE}" ]; then
    echo "AGENT_CONFIG_FILE environment variable not set."
    exit 2
fi

if [ $# -lt 1 ]; then
    echo "Usage: ${0} <commit hash>"
    exit 2
fi

AGENT_ENTRY_POINT=$(realpath "${SCRIPT_DIR}/../../scalyr_agent/agent_main.py")
AGENT_CONFIG_FILE=$(realpath "${SCRIPT_DIR}/../../${AGENT_CONFIG_FILE}")

AGENT_START_COMMAND="python ${AGENT_ENTRY_POINT} start --no-fork --no-change-user --config=${AGENT_CONFIG_FILE}"

CAPTURE_METRICS_SCRIPT_PATH=$(realpath "${SCRIPT_DIR}/send_usage_data_to_codespeed.py")

# How long to run the agent process and capture the metrics for (in seconds)
RUN_TIME=${RUN_TIME-"60"}

# How often to capture metrics during the capture run time (in seconds)
CAPTURE_INTERVAL=${CAPTURE_INTERVAL-"10"}

echo "Starting the agent process and metrics capture for ${RUN_TIME} seconds"
echo "Using COMMIT_DATE=${COMMIT_DATE}, COMMIT_ID=${COMMIT_HASH}, BRANCH=${CODESPEED_BRANCH}"

# 1. Start the agent
echo "Starting agent process..."
echo "Using command line options: ${AGENT_START_COMMAND}"

${AGENT_START_COMMAND} 2>&1 &
AGENT_PROCESS_PID=$!

# NOTE: We use a trap to ensure this function is always executed, even if some command in this
# script returns non-zero. This way we ensure we always clean up correctly.
cleanup() {
    echo "Run completed, stopping the agent process."
    # First give it some time to gracefully shut down
    kill -s SIGINT ${AGENT_PROCESS_PID} || true
    sleep 2
    kill -9 ${AGENT_PROCESS_PID} 2> /dev/null || true
}

trap cleanup EXIT

# 2. Start the capture script - note this script will wait and block until
# RUN_TIME seconds have passed
CAPTURE_SCRIPT_COMMAND="${CAPTURE_METRICS_SCRIPT_PATH} \
    --pid=${AGENT_PROCESS_PID} \
    --capture-time=${RUN_TIME} \
    --capture-interval=${CAPTURE_INTERVAL} \
    --codespeed-url=\"${CODESPEED_URL}\" \
    --codespeed-auth=\"${CODESPEED_AUTH}\" \
    --codespeed-project=\"${CODESPEED_PROJECT}\" \
    --codespeed-executable=\"${CODESPEED_EXECUTABLE}\" \
    --codespeed-environment=\"${CODESPEED_ENVIRONMENT}\" \
    --branch=\"${CODESPEED_BRANCH}\" \
    --commit-date=\"${COMMIT_DATE}\" \
    --commit-id=\"${COMMIT_HASH}\" \
    --debug"

echo "Starting the metrics capture script..."
# shellcheck disable=SC2086
eval ${CAPTURE_SCRIPT_COMMAND}
