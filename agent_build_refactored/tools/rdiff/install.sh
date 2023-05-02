#!/usr/bin/env bash

set -e

apt update
apt install -y rdiff

SCRIPTS_DIR="/scripts"
mkdir -p "${SCRIPTS_DIR}"
cp "${SOURCE_ROOT}/agent_build_refactored/tools/rdiff/create_diff.sh" "${SCRIPTS_DIR}"
cp "${SOURCE_ROOT}/agent_build_refactored/tools/rdiff/restore_from_diff.sh" "${SCRIPTS_DIR}"

#SCRIPT_DIR="$(realpath "$(dirname "${0}")")"
#
#docker build -t "${IMAGE_NAME}" -f "${SOURCE_ROOT}/agent_build_refactored/tools/rdiff/Dockerfile" "${SCRIPT_DIR}"
#
#docker save rdiff -o "${STEP_OUTPUT_PATH}/img.tar"