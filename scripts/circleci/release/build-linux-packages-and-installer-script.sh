
SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
AGENT_SOURCE_PATH="$(realpath "${SCRIPTPATH}/../../..")"

echo "$AGENT_SOURCE_PATH"

AGENT_RELEASE_VERSION=$1
echo "$AGENT_RELEASE_VERSION"
RELEASE_REPO_BASE_URL="${2:stable}"
RELEASE_REPO_NAME="${3:stable}"

OUTPUT_PATH=$4

set -e

VERSION_FILE_PATH="${AGENT_SOURCE_PATH}/VERSION"

echo "Prepare the GPG public keys."q
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

echo "Build deband rpm packages."

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
