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


pip_cache_dir="$(python3 -m pip cache dir)"

# Reuse cached pip cache if exists.
restore_from_cache pip "$pip_cache_dir"

EXAMPLE_STEP_DIR="$SOURCE_ROOT/agent_build/tools/tests/fixtures/example_steps"
sh_cs python3 -m pip install -r "${EXAMPLE_STEP_DIR}/requirements-1.txt"
sh_cs python3 -m pip install -r "${EXAMPLE_STEP_DIR}/requirements-2.txt"


tmp_dir=$(sh_cs mktemp -d)
restore_from_cache webdriver "$tmp_dir/webdriver"

# Download the webdriver if it doesn't exist.
if [ ! -d "$tmp_dir/webdriver" ]; then
  log "Download webdriver."
  sh_c mkdir "$tmp_dir/webdriver"
  sh_cs curl -L https://github.com/mozilla/geckodriver/releases/download/v0.30.0/geckodriver-v0.30.0-linux64.tar.gz > "$tmp_dir/webdriver.tar.gz"
  sh_c tar -xf "$tmp_dir/webdriver.tar.gz" -C "$tmp_dir/webdriver"
fi

# Save pip cache under the "pip" key to reuse it in future.
save_to_cache pip "$pip_cache_dir"
# Save webdriver in the cache under the "webdriver" key.
save_to_cache webdriver "$tmp_dir/webdriver"
