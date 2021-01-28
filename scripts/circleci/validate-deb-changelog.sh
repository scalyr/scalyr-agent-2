#!/usr/bin/env bash
# Script which verifies that the changelog formatting in the provided debian package is valid
set -e

DEB_FILE_PATH=$1

if [ ! -f "${DEB_FILE_PATH}" ]; then
  echo "File ${DEB_FILE_PATH} doesn't exist"
  exit 1
fi

echo "Using file ${DEB_FILE_PATH}"

dpkg -X "${DEB_FILE_PATH}" /tmp/deb_package > /dev/null

set +e

stderr=$(dpkg-parsechangelog --file /tmp/deb_package/usr/share/doc/scalyr-agent-2/changelog.gz 2>&1 1> /dev/null)

if [[ "$?" -ne 0 ]]; then
  >&2 echo "$stderr"
  exit 1
fi

set -e

warnings=$(grep warning <<< "$stderr" || true)

if [[ -n "${warnings}" ]]; then
  >&2 echo "The debian package changelog is built with warnings. This may be caused by splitting the text across miltiple lines."
  >&2 echo -e "$warnings"
  >&2 echo -e "$stderr"
  exit 1
fi

echo "Changelog in ${DEB_FILE_PATH} file is valid"
exit 0
