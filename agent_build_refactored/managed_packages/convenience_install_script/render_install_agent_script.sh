# Copyright 2014-2023 Scalyr Inc.
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

# This script renders agent's "convenience" install script and puts required URLs in it.

set -e

PARENT_DIR="$(dirname "${0}")"

APT_REPO_URL="${1}"
YUM_REPO_URL="${2}"
PUBLIC_KEY_URL="${3}"
OUTPUT_PATH="${4}"


TEMPLATE_PATH="${PARENT_DIR}/install_agent_template.sh"

mkdir -p "$(dirname "${OUTPUT_PATH}")"

CONTENT=$(cat "${TEMPLATE_PATH}")

CONTENT="${CONTENT/\{ % REPLACE_APT_REPOSITORY_URL % \}/$APT_REPO_URL}"
CONTENT="${CONTENT/\{ % REPLACE_YUM_REPOSITORY_URL % \}/$YUM_REPO_URL}"
CONTENT="${CONTENT/\{ % REPLACE_PUBLIC_KEY_URL % \}/$PUBLIC_KEY_URL}"

echo "${CONTENT}" > "${OUTPUT_PATH}"

