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

# Script which runs lint checks utilizing shellcheck on shell scripts in this
# repo.

set -e

IGNORE_BINARY_DOESNT_EXIST=${IGNORE_BINARY_DOESNT_EXIST:-"1"}

if ! which shellcheck > /dev/null 2>&1; then
    echo "shellcheck binary doesn't exist"

    if [ "${IGNORE_BINARY_DOESNT_EXIST}" -ne "0" ]; then
        echo "Skipping checks..."
        exit 0
    else
        exit 1
    fi
fi

SHELLCHECK_VERSION=$(shellcheck --version)
echo "Using shellcheck: ${SHELLCHECK_VERSION}"

# TODO: Fix various warnings in scripts in .circleci/ directory and then bump up
# the severity to warning
shellcheck -S error $(find . -name "*.sh" | grep -v .tox | grep -v virtualenv)
shellcheck -S warning benchmarks/scripts/*.sh
shellcheck -S warning installer/scripts/*.sh
