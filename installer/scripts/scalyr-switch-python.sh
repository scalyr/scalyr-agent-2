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


# This script is used by rpm and deb packages to switch on available python interpreter after installation.
# Also, it can be used to switch between python interpreters
# usage: scalyr-switch-python.sh python2|python3

set -e

if [ $# -lt 1 ]; then
  echo "Usage: ${0} <default|python2|python3>"
  exit 2
fi

if [[ ${1} == "--help" || ${1} == "-h" ]]; then
  echo "Usage: ${0} <default|python2|python3>"
  echo "Switch python interpreter version for Scalyr agent."
  echo "'default' or 'python' - use python interpreter which is mapped on to 'python' command (#!/usr/bin/env python)"
  echo "'python2' - use python interpreter which is mapped on to 'python2' command (#!/usr/bin/env python2)"
  echo "'python3' - use python interpreter which is mapped on to 'python3' command (#!/usr/bin/env python3)"

  exit 0
fi

if [  "${1}" != "default" ] && [  "${1}" != "python2" ] && [ "${1}" != "python3" ]; then
  echo "Invalid value: ${1}."
  echo "Usage: ${0} <default|python2|python3>"
  echo "Use --help for more detils."
  exit 2
fi


if [  "${1}" == "default" ] || [  "${1}" == "python" ]; then
  EXECUTABLE_NAME="python"
elif [  "${1}" == "python2" ]; then
    EXECUTABLE_NAME="python2"
elif [  "${1}" == "python3" ]; then
    EXECUTABLE_NAME="python3"
else
  echo "Invalid value: ${1}."
  echo "Usage: ${0} <default|python2|python3>"
  echo "Use --help for more detils."
  exit 2
fi

/usr/bin/env "${EXECUTABLE_NAME}" /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --set-python="${EXECUTABLE_NAME}"