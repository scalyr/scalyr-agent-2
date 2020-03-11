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

echo "Check for python."
# if command was not successful, print hint message and exit.
if ! /usr/bin/env python --version; then
  echo -e "\e[31mCommand 'python' is not found.\e[0m"
  echo "You can install it by running command:"
  # get 'ID_LIKE' and 'ID' fields from '/etc/os-release' file and then search for distributions key words.
  if [[ -f "/etc/os-release" ]]; then
    found_distros=$(grep -E "^ID_LIKE=|^ID=" /etc/os-release)
    # debian and etc.
    if echo "${found_distros}" | grep -qE "debian|ubuntu"; then
      echo "'apt install python'"
      echo "or"
      echo "apt install python3"
    # RHEL and etc.
    elif echo "${found_distros}" | grep -qE "rhel|centos|fedora"; then
      echo "'yum install python2'"
      echo "or"
      echo "'yum install python3'"
    fi
  fi
  exit 1
fi

echo "Check python version."

current_version=$(/usr/bin/env python --version 2>&1 | grep -o "[0-9].[0-9].")

# shellcheck disable=SC2072
if [[ "$current_version" < "2.6" ]]; then
  echo -e "\e[31mThe python interpreter with version '>=2.6 or >=3.5' is required. Current version: ${current_version}. Aborting.\e[0m" >&2
  exit 1
fi

# shellcheck disable=SC2072
if [[ "$current_version" > "3.0" ]]; then
  if [[ "$current_version" < "3.5" ]]; then
    echo -e "\e[31mThe python interpreter with version '>=2.6 or >=3.5' is required. Current version: ${current_version}. Aborting.\e[0m" >&2
    exit 1
  fi
fi

echo -e "\e[36mPython interpreter is found. Version: ${current_version}\e[0m"

# Always remove the .pyc files and __pycache__ directories.  This covers problems for old packages that didn't have the remove in the
# preuninstall.sh script.
if [ -d /usr/share/scalyr-agent-2 ]; then
  find /usr/share/scalyr-agent-2 -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -exec rm -r {} \;
fi

exit 0
