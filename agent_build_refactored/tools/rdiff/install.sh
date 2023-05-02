#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(realpath "$(dirname "${0}")")"

docker build -t "${IMAGE_NAME}" -f "${SOURCE_ROOT}/agent_build_refactored/tools/rdiff/Dockerfile" "${SCRIPT_DIR}"

docker save rdiff -o "${STEP_OUTPUT_PATH}/img.tar"