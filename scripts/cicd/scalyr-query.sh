#!/usr/bin/env bash
# Copyright 2022 Scalyr Inc.
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

# Utility script which calls scalyr query tools and exists with non in case the provided query
# returns no results after maximum number of retry attempts has been reached. We perform multiple
# retries to make the build process more robust and less flakey and to account for delayed
# ingestion for any reason.

set -e

RETRY_ATTEMPTS=${RETRY_ATTEMPTS:-"10"}
SLEEP_DELAY=${SLEEP_DELAY:-"15"}

# Script will fail if query doesn't return at least this number of results / lines
MINIMUM_RESULTS=${MINIMUM_RESULTS:-"1"}

if [ $# -eq 1 ]; then
    # Query passed in as a single string argument
    echo "Query passed in as a single string argument"
    SCALYR_TOOL_QUERY=$1
else
    # Query passed in as multiple arguments
    echo "Query passed in as multiple arguments"
    SCALYR_TOOL_QUERY="$*"
fi

echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

function retry_on_failure {
  i=1

  until [ "${i}" -gt "${RETRY_ATTEMPTS}" ]
  do
     echo_with_date ""
     # shellcheck disable=SC2145
     echo_with_date "Running function \"$@\" attempt ${i}/${RETRY_ATTEMPTS}..."
     echo_with_date ""

     exit_code=0
     "$@" && break
     exit_code=$?

     if [ "${i}" -lt "${RETRY_ATTEMPTS}" ]; then
       echo_with_date ""
       echo_with_date "Function returned non-zero status code, sleeping ${SLEEP_DELAY}s before next attempt.."
       echo_with_date ""
       sleep "${SLEEP_DELAY}"
     fi

     i=$((i+1))
  done

  if [ "${exit_code}" -ne 0 ]; then
      echo -e "\xE2\x9D\x8C Command failed to complete successfully after ${RETRY_ATTEMPTS} attempts. Exiting with non-zero." >&2
      exit 1
  fi
}

function query_scalyr {
    echo_with_date "Using query '${SCALYR_TOOL_QUERY}'"

    RESULT=$(eval "scalyr query '${SCALYR_TOOL_QUERY}' --columns='timestamp,severity,message' --start='20m' --count='100' --output multiline")
    RESULT_LINES=$(echo -e "${RESULT}" | sed '/^$/d' | wc -l)

    echo_with_date "Results for query '${SCALYR_TOOL_QUERY}':"
    echo_with_date ""
    echo -e "${RESULT}"

    if [ "${RESULT_LINES}" -lt ${MINIMUM_RESULTS} ]; then
        echo_with_date ""
        echo_with_date "Expected at least ${MINIMUM_RESULTS} matching lines, got ${RESULT_LINES}."
        return 1
    fi

    echo_with_date ""
    echo -e "\xE2\x9C\x94 Found ${RESULT_LINES} matching log lines"
    return 0
}

retry_on_failure query_scalyr
