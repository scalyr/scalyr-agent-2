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

# Script which copies cached Docker images to ~/agent_image/ directory
mkdir -p ~/agent_image
mkdir -p ~/fpm_builder_cache
mkdir -p ~/monitors_builder_cache
mkdir -p ~/agent_image_cache

echo "==================================================================="
echo "Checking fpm_builder_cache."
ls ~/fpm_builder_cache
if [ "$(ls -A ~/fpm_builder_cache)" ]; then
    echo "fpm builder image is found."
    cp ~/fpm_builder_cache/* ~/agent_image/
else
  echo "fpm builder image is not found."
fi
echo "==================================================================="
echo "Checking monitors_builder_cache."
ls ~/monitors_builder_cache
if [ "$(ls -A ~/monitors_builder_cache/scalyr-agent-testings-monitor-base)" ]; then
    echo "monitors builder image is found."
    cp ~/monitors_builder_cache/scalyr-agent-testings-monitor-base ~/agent_image/
else
  echo "monitors builder image is not found."
fi
echo "==================================================================="
echo "Checking agent_image_cache."
ls ~/agent_image_cache
# the agent distribution image name should match to this glob.
if [ "$(ls -A ~/agent_image_cache/scalyr-agent-testings-distribution-*-base)" ]; then
    echo "agent image cache image is found."
    cp ~/agent_image_cache/scalyr-agent-testings-distribution-*-base ~/agent_image/
else
  echo "agent image cache image is not found."
fi
