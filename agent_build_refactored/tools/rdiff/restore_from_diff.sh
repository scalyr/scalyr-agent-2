#!/usr/bin/env bash


set -e
ORIGINAL_FILE="${1}"
DELTA_FILE="${2}"
RESTORED_FILE="${3}"

rdiff patch "${ORIGINAL_FILE}" "${DELTA_FILE}" "${RESTORED_FILE}"