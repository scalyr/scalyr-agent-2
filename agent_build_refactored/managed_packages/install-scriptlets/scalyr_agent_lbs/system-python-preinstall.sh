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

# This script check for installed python interpreter with opropriate version.
# In some distributions, there is no 'python' command even if python interpreter is installed.
# In this cases script have to exit with an error.
# This is important because all agent scripts rely on '/usr/bin/env python' command.

# Verify the provided version of the Python meets the minimum requirements.
test_python_version() {
  local command=$1
  local version=$2
  local min_version=$3

  if test "$(echo "$version" "$min_version" | xargs -n1 | sort -V | head -n1)" == "$version" ; then
    echo "- command $command [$version] is found but the minimum required version is '${min_version}'."
    return 1
  fi

  return 0
}

# Verify if provided command like 'python2' or 'python3' exists and meets minimum version requirements.
is_python_valid() {
  local command=$1
  local version

    # Requirements
  local MIN_REQ_PYTHON3_VERSION="3.6"

  # We also look for Python3 inside /usr/local as an additional fallback
  PATH="${PATH}:/ust/local/sbin:/usr/local/bin"
  echo ". Searching for ${command} in PATH \"${PATH}\":"


  version=$(/usr/bin/env "${command}" --version 2>&1 | grep -Eo "[0-9](.[0-9]+)+")
  local exit_code=$?

  if [[ -z "${version}" || "${exit_code}" -ne "0" ]]; then
      echo "- command $command not found."
      return 1
  fi

  case ${version::1} in
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

if ! is_python_valid "python3" ; then
  echo "! Suitable Python interpreter not found."
  # get 'ID_LIKE' and 'ID' fields from '/etc/os-release' file and then search for distributions key words.
  if [[ -f "/etc/os-release" ]]; then
    echo "You can install it by running command:"
    found_distros=$(grep -E "^ID_LIKE=|^ID=" /etc/os-release)
    # debian and etc.
    if echo "${found_distros}" | grep -qE "debian|ubuntu"; then
      echo -e "'apt install python3'"
    # RHEL and etc.
    elif echo "${found_distros}" | grep -qE "rhel|centos|fedora"; then
      echo -e "'yum install python3'"
    fi
  fi
  exit 1
fi
