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

for FILE in scalyr_agent/builtin_monitors/*.py; do
    MONITOR_MODULE=$(echo "${FILE}" | tr "/" "." | sed "s/\.py//")
    MONITOR_NAME=$(basename "${FILE}" | sed "s/\.py//")

    if [ "${MONITOR_NAME}" = "__init__" ]; then
        continue
    fi

    echo "Generating docs for module: ${MONITOR_MODULE}"
    # TODO: Also write those values to the generated files. Right now our docs files consist of
    # manual + auto generated changes. We should better organize those so auto generated sections
    # can be kept up to date automatically.
    # python print_monitor_doc.py "${MONITOR_MODULE}" > "docs/monitors/${MONITOR_NAME}.md"
    python print_monitor_doc.py "${MONITOR_MODULE}"
done
