#!/bin/sh
# Copyright 2014-2021 Scalyr Inc.
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

# This script is used by "ShellScriptDeploymentStep"
# (See more in class "ShellScriptDeploymentStep" in the "agent_build/tools/environment_deployments/deployments.py"

# This script is used in the deployment step that build base image for the alpine based agent docker images.
# This file is sourced by one of the actual shell scripts that has to build the base image.

set -e

# source main library, all needed functions are in there.
. "$SOURCE_ROOT/agent_build/tools/environment_deployments/steps/build_base_docker_image/build_base_images_common_lib.sh"

# Build base images are based on the python-alpine dockerhub image.
build_all_base_images alpine