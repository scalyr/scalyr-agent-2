#!/usr/bin/env bash
# Script which verifies that the changelog formatting in the provided rpm package is valid
set -e

RPM_FILE_PATH=$1

if [ ! -f "${RPM_FILE_PATH}" ]; then
  echo "File ${RPM_FILE_PATH} doesn't exist"
  exit 1
fi

echo "Using file ${RPM_FILE_PATH}"

set +e

OUTPUT=$(rpm -qp --changelog "${RPM_FILE_PATH}")
EXIT_CODE=$?

set -e

if [ "${EXIT_CODE}" -ne 0 ]; then
    echo "Changelog in the provided rpm package is not valid"
    echo -e "${OUTPUT}"
    rpm -qip "${RPM_FILE_PATH}"
    exit 2
fi

echo "Changelog in ${RPM_FILE_PATH} file is valid"
exit 0
