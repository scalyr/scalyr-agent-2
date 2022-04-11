#!/usr/bin/env sh

set -e

echo "${INPUT}_shell" | tr -d "\n"  >> "${BASE_RESULT_FILE_PATH}"