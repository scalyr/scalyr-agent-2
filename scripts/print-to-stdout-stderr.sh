#!/usr/bin/env bash
# Copyright 2020 Scalyr Inc.
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

# Script which prints a line to stdout and stderr every SLEEP_DELAY seconds

SLEEP_DELAY=${SLEEP_DELAY:-"2"}

echo ""
echo "Using sleep delay of ${SLEEP_DELAY} seconds"
echo ""

for i in {1..1000000}; do
    echo "stdout: line $i"
    echo "stderr: line $i" 1>&2
    echo -n "line $i BEGIN DELAYED MESSAGE stdout"
    echo -n "line $i BEGIN DELAYED MESSAGE stderr" 1>&2
    sleep "${SLEEP_DELAY}"
    echo "-END DELAYED MESSAGE stdout line $i"
    echo "-END DELAYED MESSAGE stderr line $i" 1>&2
done
