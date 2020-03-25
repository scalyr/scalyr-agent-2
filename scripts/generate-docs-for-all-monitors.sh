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

# Script which takes care of generating fragments of monitor documentation which can be generated
# from the monitors code.
#
# It writes generated documentation files to docs/monitors/<monitor name>.md

set -e

# Marker in the Markdown file which marks the line after which automatically generated content
# should be appended
AUTO_GENERATED_SECTION_MARKER="<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->"

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")

MONITOR_FILES=$(find scalyr_agent/builtin_monitors/ -maxdepth 1 -type f -name "*monitor.py" -o -name "*linux*.py")

# shellcheck disable=SC2068
for FILE in ${MONITOR_FILES[@]}; do
    MONITOR_MODULE=$(echo "${FILE}" | tr "/" "." | sed "s/\.py//")
    MONITOR_NAME=$(basename "${FILE}" | sed "s/\.py//")
    DOC_FILE="docs/monitors/${MONITOR_NAME}.md"

    echo "Generating docs for module: ${MONITOR_MODULE} -> ${DOC_FILE}"

    if [ ! -f "${DOC_FILE}" ]; then
        echo "File ${DOC_FILE} doesn't exist, skipping..."
        continue
    fi

    # Skip file without the marker
    set +e
    grep "${AUTO_GENERATED_SECTION_MARKER}" "${DOC_FILE}" > /dev/null
    EXIT_CODE=$?
    set +e

    if [ "${EXIT_CODE}" -eq 1 ]; then
        continue
    fi

    AUTO_GENERATED_CONTENT=$(python "${SCRIPT_DIR}/print_monitor_doc.py" "${MONITOR_MODULE}" --no-warning --include-sections='description,configuration_reference,log_reference,metrics')
    CONTENT_WITHOUT_AUTO_GENERATED_PART=$(perl -0777 -p -e 's/(.*'"${AUTO_GENERATED_SECTION_MARKER}"').*/$1/s' "${DOC_FILE}")
    NEW_CONTENT=$(echo -e "${CONTENT_WITHOUT_AUTO_GENERATED_PART}\n\n${AUTO_GENERATED_CONTENT}")
    echo -e "${NEW_CONTENT}" > "${DOC_FILE}"
done
