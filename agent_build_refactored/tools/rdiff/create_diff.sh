#!/usr/bin/env bash


set -e

ORIGINAL_FILE="${1}"
NEW_FILE="${2}"
SIGNATURE_FILE="${3}"
DELTA_FILE="${4}"


rdiff signature "${ORIGINAL_FILE}" "${SIGNATURE_FILE}"
rdiff delta "${SIGNATURE_FILE}" "${NEW_FILE}" "${DELTA_FILE}"
