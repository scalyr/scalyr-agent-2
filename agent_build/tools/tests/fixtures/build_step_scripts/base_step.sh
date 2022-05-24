#!/usr/bin/env sh

set -e

result_string="${INPUT}_shell"

if [ -n "$AGENT_BUILD_IN_DOCKER" ]; then
  result_string="${result_string}_in_docker"
fi

echo "${result_string}" | tr -d "\n"  >> "${BASE_RESULT_FILE_PATH}"
