#!/bin/sh
# Copyright 2014-2021 Scalyr Inc.
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

DEPENDENCY_STEP_OUTPUT="$1"

cat "${BASE_RESULT_FILE_PATH}" >> "$STEP_OUTPUT_PATH/result.txt"
echo "" >> "$STEP_OUTPUT_PATH/result.txt"

cat "${DEPENDENCY_STEP_OUTPUT}/result.txt" >> "$STEP_OUTPUT_PATH/result.txt"
echo "" >> "$STEP_OUTPUT_PATH/result.txt"

echo "${INPUT}_shell" | tr -d "\n" >> "$STEP_OUTPUT_PATH/result.txt"