#!/usr/bin/env bash
#
# Copyright 2014-2021 Scalyr Inc.
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
#
# =========================================================================
#
# This script is used to create build linux based packages agent, install script and other related things.
# For now it is supposed to work only within the circleci job.
# Usage: build-linux-packages-and-installer-script.sh <AGENT_RELEASE_VERSION> <OUTPUT_PATH> <RELEASE_REPO_BASE_URL> <RELEASE_REPO_NAME>
#
# AGENT_RELEASE_VERSION - the version for the agent to set. The version form the VERSION file is used if emoty.
# OUTPUT_PATH - the path for all build artifacts.
# RELEASE_REPO_BASE_URL - the base url for the different types of release S3 repos (stable, beta, internal).
# RELEASE_REPO_NAME - the type of the S3 repo (stable, beta, internal).

set -e

SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
AGENT_SOURCE_PATH="$(realpath "${SCRIPTPATH}/../../..")"

AGENT_RELEASE_VERSION=$1

OUTPUT_PATH="$(realpath "$2")"
RELEASE_REPO_BASE_URL=${3:-stable}
RELEASE_REPO_NAME=${4:-stable}

VERSION_FILE_PATH="${AGENT_SOURCE_PATH}/VERSION"

echo "Prepare the GPG public keys."
gpg --update-trustdb

# import remote sign machine public keys from files in the Scalyr agent repo.
# gnupg < 2.1
#GPG_SIGNING_KEYID=`gpg --with-fingerprint "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/main.asc" | grep "Key fingerprint" | awk '{print $10$11$12$13}'`
#GPG_ALT_SIGNING_KEYID=`gpg --with-fingerprint "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/alt.asc" | grep "Key fingerprint" | awk '{print $10$11$12$13}'`

# gnupg > 2.1
GPG_SIGNING_KEYID=$(gpg --with-fingerprint --with-colons --import-options show-only --import < "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/main.asc" | grep "fpr:" | head -1 | awk -F ":" '{print $10}')
GPG_ALT_SIGNING_KEYID=$(gpg --with-fingerprint --with-colons --import-options show-only --import < "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/alt.asc" | grep "fpr:" | head -1 | awk -F ":" '{print $10}')

echo "Using GPG_SIGNING_KEYID=${GPG_SIGNING_KEYID}"
echo "Using GPG_ALT_SIGNING_KEYID=${GPG_ALT_SIGNING_KEYID}"

# import gpg public keys.
gpg --import "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/main.asc"
gpg --import "${AGENT_SOURCE_PATH}/scripts/circleci/release/public_keys/alt.asc"

if [ -n "${AGENT_RELEASE_VERSION}" ]; then
  agent_version="${AGENT_RELEASE_VERSION}"
else
  agent_version="$(cat "${VERSION_FILE_PATH}").dev1-$(git rev-parse --short HEAD)"
fi

echo "${agent_version}" > "${VERSION_FILE_PATH}"

echo "Build deb and rpm packages."

pushd "${OUTPUT_PATH}"

python "${AGENT_SOURCE_PATH}/build_package.py" deb
python "${AGENT_SOURCE_PATH}/build_package.py" rpm


DEB_PACKAGE_PATH="$OUTPUT_PATH/$(ls --color=none *.deb)"
RPM_PACKAGE_PATH="$OUTPUT_PATH/$(ls --color=none *.rpm)"

echo "$DEB_PACKAGE_PATH"

"${AGENT_SOURCE_PATH}/scripts/circleci/validate-deb-changelog.sh" "${DEB_PACKAGE_PATH}"
"${AGENT_SOURCE_PATH}/scripts/circleci/validate-rpm-changelog.sh" "${RPM_PACKAGE_PATH}"


echo "Build deb and rpm repo packages and installer script."

bash ${AGENT_SOURCE_PATH}/scripts/circleci/release/create-agent-installer.sh "$GPG_SIGNING_KEYID" "$GPG_ALT_SIGNING_KEYID" "$RELEASE_REPO_BASE_URL" "$RELEASE_REPO_NAME"

cat "${VERSION_FILE_PATH}" > RELEASE_VERSION

popd