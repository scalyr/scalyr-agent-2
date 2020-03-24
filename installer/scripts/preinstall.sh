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


echo "Checking Python version." >&2

current_version2=$(/usr/bin/env python2 --version 2>&1 | grep -o "[0-9].[0-9]")
current_version3=$(/usr/bin/env python3 --version 2>&1 | grep -o "[0-9].[0-9]")

python2_found=false
python3_found=false

if [[ -n "${current_version2}" ]]; then
  # shellcheck disable=SC2072
  if [[ "$current_version2" > "2.5" ]]; then
    python2_found=true
    echo "Suitable python interpreter is found: ${current_version2}."
  else
    echo -e "Python interpreter is found, but its version (${current_version2}) less than required (2.6)."
  fi
fi

if [[ -n "${current_version3}" ]]; then
  # shellcheck disable=SC2072
  if [[ "$current_version3" > "3.4" ]]; then
    python3_found=true
    echo "Suitable python interpreter is found: ${current_version3}."
  else
    echo -e "Python interpreter is found, but its version (${current_version3}) less than required (3.5)."
#    echo -e "\e[31mThe python interpreter with version '>=2.6 or >=3.5' is required. Current version: ${current_version2}. Aborting.\e[0m" >&2
  fi
fi

if [[ ${python2_found} == false ]] && [[ ${python3_found} == false ]]; then
  echo -e "\e[31mPython interpreter is not found.\e[0m"
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


# Always remove the .pyc files and __pycache__ directories.  This covers problems for old packages that didn't have the remove in the
# preuninstall.sh script.
if [ -d /usr/share/scalyr-agent-2 ]; then
  find /usr/share/scalyr-agent-2 -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -exec rm -r {} \;
fi

exit 0
