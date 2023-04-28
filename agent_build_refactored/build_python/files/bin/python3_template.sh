#!/usr/bin/env bash
# Copyright 2014-2023 Scalyr Inc.
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

#
# This script runs given Python executable with additional paths in the 'LD_LIBRARY_PATH' that
# depend on which OpenSSL libraries are used. If package is configured to use embedded OpenSSL, then
# it adds path to the embedded OpenSSL shared objects, if not, it skips that, so system's dynamic linker
# has to find it.
#
#
# This script is a wrapper that calls real Python executable with additional path for  'LD_LIBRARY_PATH' variable in
# order make Python work.
#

set -e

PYTHON_EXECUTABLE="%{{ REPLACE_PYTHON_EXECUTABLE }}"
ADDITIONAL_LD_LIBRARY_PATH="%{{ REPLACE_ADDITIONAL_LD_LIBRARY_PATH }}"

export LD_LIBRARY_PATH="${ADDITIONAL_LD_LIBRARY_PATH}:${LD_LIBRARY_PATH}"
exec "${PYTHON_EXECUTABLE}" "$@"
