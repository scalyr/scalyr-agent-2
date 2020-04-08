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
mkdir -p ~/agent_image_cache

if [ "$(ls -A ~/fpm_builder_cache)" ]; then
    echo "fpm builder image is found."
    cp ~/fpm_builder_cache/* ~/agent_image/
fi

if [ "$(ls -A ~/agent_image_cache)" ]; then
    echo "agent image cache image is found."
    cp ~/agent_image_cache/* ~/agent_image/
fi
