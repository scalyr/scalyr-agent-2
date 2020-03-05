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

# 2. Start the capture script - note this script will wait and block until
# RUN_TIME seconds have passed

AGENT_PID_FILE_PATH="/scalyr-data"

AGENT_PROCESS_PID=$(cat "${AGENT_PID_FILE_PATH}/log/agent.pid")

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
    ${ADDITIONAL_CAPTURE_SCRIPT_FLAGS} \
    --debug"

echo "Starting the metrics capture script (ADDITIONAL_CAPTURE_SCRIPT_FLAGS=${ADDITIONAL_CAPTURE_SCRIPT_FLAGS})..."
# shellcheck disable=SC2086
eval ${CAPTURE_SCRIPT_COMMAND}
