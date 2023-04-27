#!/usr/bin/env bash
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

# This script compiles final source for nodejs based actions.

set -e

SCRIPT_PATH="$(realpath "${0}")"
PARENT_PATH="$(dirname "${SCRIPT_PATH}")"
SOURCE_ROOT="$(dirname "$(dirname "$(dirname "${PARENT_PATH}")")")"

echo "$SOURCE_ROOT"

# shellcheck disable=SC2164
pushd "${PARENT_PATH}"

rm -rf "${PARENT_PATH:?}/node_modules"

# Install dependencies for all actions in a centralized node_modules folder.
npm install


actions=(
  "restore_steps_caches"
)

# Go through all nodejs actions and compile required source
for action_name in "${actions[@]}"; do
	ACTION_PATH="${SOURCE_ROOT}/.github/actions/${action_name}"
	# ncc does not work properly when node_modules does not exist in the actions folder, so we make a symlink
	ln -s -f "${PARENT_PATH}/node_modules" "${ACTION_PATH}/node_modules"
	# Finally compile the action's source
	"${PARENT_PATH}/node_modules/.bin/ncc" build "${ACTION_PATH}/index.js" -o "${ACTION_PATH}/dist"
done

