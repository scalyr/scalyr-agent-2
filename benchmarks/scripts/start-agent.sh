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

AGENT_SOURCE_PATH="/agent-source"
mkdir -p "${AGENT_SOURCE_PATH}"
echo "Clone agent repository."
git clone "${AGENT_GIT_URL}" "${AGENT_SOURCE_PATH}"
cd "${AGENT_SOURCE_PATH}"
if [[ "${COMMIT_SHA1}" ]]; then
  echo "Checkout to target commit. ${COMMIT_SHA1}"
  git checkout "${COMMIT_SHA1}"
else
  echo "Stay on master."
fi

cp /config/config.json /config.json
echo "api_key: \"${SCALYR_API_KEY}\"", >> /config.json
echo "scalyr_server: \"${SCALYR_SERVER}\"", >> /config.json
echo "server_attributes: {serverHost: \"${SERVER_HOST}\"}", >> /config.json
echo "${AGENT_CONFIG_ADDITIONAL_FIELDS}" >> /config.json
echo "}" >> /config.json

cat /config.json
mkdir -p ~/scalyr-agent-dev/{log,config,data}
python /agent-source/scalyr_agent/agent_main.py start --no-fork --no-change-user --config=/config.json
