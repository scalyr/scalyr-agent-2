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

# Script which copies Docker images created during test runs to directory which
# is cached
whoami
ls ~/agent_image/
if [ -f ~/agent_image/scalyr-agent-testings-fpm_package-builder ]; then
    echo "Copy image 'scalyr-agent-testings-fpm_package-builder' to cache."
    cp  ~/agent_image/scalyr-agent-testings-fpm_package-builder ~/fpm_builder_cache/scalyr-agent-testings-fpm_package-builder
    rm ~/agent_image/scalyr-agent-testings-fpm_package-builder
else
  echo "Image 'scalyr-agent-testings-fpm_package-builder' is not found."
fi

if [ -f ~/agent_image/scalyr-agent-testings-monitor-base ]; then
    echo "Copy image 'scalyr-agent-testings-monitor-base' to cache."
    cp  ~/agent_image/scalyr-agent-testings-monitor-base ~/monitors_builder_cache/scalyr-agent-testings-monitor-base
    rm ~/agent_image/scalyr-agent-testings-monitor-base
else
  echo "Image 'scalyr-agent-testings-monitor-base' is not found."
fi

whoami
ls ~/agent_image/
cp ~/agent_image/* ~/agent_image_cache/
