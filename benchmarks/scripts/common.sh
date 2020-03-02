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

# Script which contains common environment variable definitions and "is set"
# checks which are used by all the benchmark scripts.

MANDATORY_ENV_VARIABLES=(CODESPEED_URL CODESPEED_AUTH CODESPEED_PROJECT CODESPEED_EXECUTABLE CODESPEED_ENVIRONMENT CODESPEED_BRANCH COMMIT_DATE)
COMMIT_DATE=${COMMIT_DATE-""}

# shellcheck disable=SC2034
COMMIT_HASH=${1}

# Verify mandatory environment variables are set
function verify_mandatory_common_env_variables_are_set() {
    for var_name in "${MANDATORY_ENV_VARIABLES[@]}"; do
        if [ -z "${!var_name}" ]; then
            echo "${var_name} environment variable not set."
            exit 2
        fi
    done
}
