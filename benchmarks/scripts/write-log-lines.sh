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

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")

CAPTURE_METRICS_SCRIPT_PATH=$(realpath "${SCRIPT_DIR}/write-log-lines.py")



python "${CAPTURE_METRICS_SCRIPT_PATH}" \
  --agent-data-path="${AGENT_DATA_PATH}" \
  --debug \
  ${LOG_WRITER_ADDITIONAL_ARGS}

