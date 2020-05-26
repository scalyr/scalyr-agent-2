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

# Script which verifies codecov.yml config syntax with codecov.io.
# It takes occasional codecov API failures (timeouts) into account and tries to
# retry on failure.
MAX_ATTEMPTS=${MAX_ATTEMPTS:-5}
RETRY_DELAY=${RETRY_DELAY:-5}

# Work around for temporary codecov API timing out
for (( i=0; i<$MAX_ATTEMPTS; ++i)); do
    OUTPUT=$(curl --max-time 10 --data-binary @codecov.yml https://codecov.io/validate)
    CURL_EXIT_CODE=$?
    echo "${OUTPUT}" | grep -i "Valid!" > /dev/null
    GREP_EXIT_CODE=$?

    if [ "${GREP_EXIT_CODE}" -eq 0 ]; then
        echo ""
        echo "codecov.yml config is valid."
        break
    fi

    echo ""
    echo "curl output: ${OUTPUT}"
    echo ""

    if [ "${CURL_EXIT_CODE}" -eq 28 ]; then
        # curl exists with 28 on timeout
        echo "Command exited with non-zero (timeout), retrying in ${RETRY_DELAY} seconds..."
        sleep "${RETRY_DELAY}"
    else
        # fatal error - we should abort immediately instead of retrying
        echo "codecov.yml config validation failed"
        exit 1
    fi
done

if [ "${GREP_EXIT_CODE}" -ne 0 ]; then
    echo "Verifying codecov.yml failed after ${MAX_ATTEMPTS} attempts"
    exit 1
fi
