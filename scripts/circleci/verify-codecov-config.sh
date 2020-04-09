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
# It takes occasional codecov API failures into account and tries to retry
# upload.

MAX_ATTEMPTS=${MAX_ATTEMPTS:-5}
RETRY_DELAY=${RETRY_DELAY:-5}

# Work around for temporary codecov API timing out
for (( i=0; i<$MAX_ATTEMPTS; ++i)); do
    curl --max-time 10 --data-binary @codecov.yml https://codecov.io/validate | grep -i 'Valid!'
    EXIT_CODE=$?

    if [ "${EXIT_CODE}" -eq 0 ]; then
        break
    fi

    echo "Command exited with non-zero, retrying in ${RETRY_DELAY} seconds..."
    sleep "${RETRY_DELAY}"
done

if [ "${EXIT_CODE}" -ne 0 ]; then
    echo "Verifying codecov.yml failed after ${MAX_ATTEMPTS} attempts"
    exit 1
fi
