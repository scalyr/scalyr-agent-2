#!/usr/bin/env bash
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

# Script which cats agent log file and runs if sanity tests have failed.

# Errors shouldn't be considered as fatal
set +e

if [ -f "scalyr_install.log" ]; then
  echo "--------------------------------------------------------------------"
  echo ""
  echo "Catting scalyr_install.log file"
  echo ""

  cat scalyr_install.log
fi


echo "--------------------------------------------------------------------"
echo ""
echo "Catting agent.log file"
echo ""

cat /var/log/scalyr-agent-2/agent.log
