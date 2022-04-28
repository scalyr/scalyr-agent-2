#!/bin/bash
# Copyright 2014-2020 Scalyr Inc.
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

# Requirements
MIN_REQ_PYTHON2_VERSION="2.7"
MIN_REQ_PYTHON3_VERSION="3.5"

INPUT_PYTHON_BIN_NAME=${1}

echo -e "\n. Searching for ${INPUT_PYTHON_BIN_NAME} in Path:\n$PATH"

test_python_version() {
  local command=$1
  local version=$2
  local min_version=$3

  if [ "$version" == "$min_version" ] ; then return 0; fi

  if test "$(echo "$version" "$min_version" | xargs -n1 | sort -V | head -n1)" == "$version" ; then
    echo "- command $command [$version] is found but the minimum required version is '${min_version}'."
    return 1
  fi

  return 0
}

is_python_valid() {
  local command=$1
  local version

  version=$(/usr/bin/env "${command}" --version 2>&1 | grep -Eo "[0-9](.[0-9]+)+")
  local exit_code=$?

  if [[ -z "${version}" || "${exit_code}" -ne "0" ]]; then
    echo "- command $command not found."
    return 1
  fi

  case ${version::1} in
    2)
      if ! test_python_version "$command" "$version" "$MIN_REQ_PYTHON2_VERSION" ; then return 1; fi
      ;;
    3)
      if ! test_python_version "$command" "$version" "$MIN_REQ_PYTHON3_VERSION" ; then return 1; fi
      ;;
    *)
      echo "- command $command found with unsupported major version $version."
      return 1
      ;;
  esac

  echo "+ command $command [$version] is found and matches the minimum required version - Success!"
  return 0
}

is_python_valid ${INPUT_PYTHON_BIN_NAME}
exit $?
