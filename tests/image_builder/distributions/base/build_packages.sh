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

PACKAGE_TYPE=${1}

echo "$(cat /agent_source/VERSION.txt)-$(git --git-dir /agent_source/.git rev-parse --short HEAD)" >/agent_source/VERSION.txt

mkdir -p /package
cd /package || exit 1
echo "${PACKAGE_TYPE}"
python /agent_source/build_package.py "${PACKAGE_TYPE}"

# change version and build new package for agent upgrade test.
echo "$(cat /agent_source/VERSION.txt)-2" >/agent_source/VERSION.txt
mkdir -p /second_package
cd /second_package || exit 1

python /agent_source/build_package.py "${PACKAGE_TYPE}"
