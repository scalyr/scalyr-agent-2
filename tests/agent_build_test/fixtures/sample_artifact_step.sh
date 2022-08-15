#!/usr/env sh
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

set -e

SAMPLE_TRACKED_FILE_PATH="${SOURCE_ROOT}/tests/agent_build_test/fixtures/sample_tracked_file.txt"

SAMPLE_TRACKED_FILE_PATH_CONTENT=$(cat "${SAMPLE_TRACKED_FILE_PATH}")

message="$INPUT ${SAMPLE_TRACKED_FILE_PATH_CONTENT}"
echo "The resulting step output: ${message}"

echo "${message}" > "${STEP_OUTPUT_PATH}/result.txt"