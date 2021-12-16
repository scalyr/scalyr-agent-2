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

# NOTE: This script is a part of the explanatory example of how Deployments work and it is not used in the real code.
# This script is used by "ShellScriptDeploymentStep"
# (See more in class "ShellScriptDeploymentStep" in the "agent_build/tools/environment_deployments/deployments.py"

# Just ls the VERSION file. It exist in original source root, but it is not tracked by the step so it has to
# be unavailable and raise error.
sh_c ls -al "${SOURCE_ROOT}/VERSION"

