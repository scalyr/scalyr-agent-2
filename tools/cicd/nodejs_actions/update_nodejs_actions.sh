#!/usr/bin/env bash

set -e

SCRIPT_PATH="$(realpath "${0}")"
PARENT_PATH="$(dirname "${SCRIPT_PATH}")"
SOURCE_ROOT="$(dirname "$(dirname "$(dirname "${PARENT_PATH}")")")"

echo "$SOURCE_ROOT"

# shellcheck disable=SC2164
pushd "${PARENT_PATH}"

rm -rf "${PARENT_PATH:?}/node_modules"
npm install


actions=(
  "restore_steps_caches"
)
for action_name in "${actions[@]}"
do
	echo "$action_name"
	ACTION_PATH="${SOURCE_ROOT}/.github/actions/${action_name}"
	ln -s -f "${PARENT_PATH}/node_modules" "${ACTION_PATH}/node_modules"
	"${PARENT_PATH}/node_modules/.bin/ncc" build "${ACTION_PATH}/index.js" -o "${ACTION_PATH}/dist"
done

