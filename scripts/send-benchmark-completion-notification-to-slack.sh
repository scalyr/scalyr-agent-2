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

# Script which sends notification about finished CodeSpeed agent process level benchmark with
# corresponding screenshots to Slack.

SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")

sed -i "s#IMAGE_URL_1#$1#g" "${SCRIPT_DIR}/slack_payload.json"
sed -i "s#IMAGE_URL_2#$2#g" "${SCRIPT_DIR}/slack_payload.json"
sed -i "s#IMAGE_URL_3#$3#g" "${SCRIPT_DIR}/slack_payload.json"
sed -i "s#IMAGE_URL_4#$4#g" "${SCRIPT_DIR}/slack_payload.json"

cat "${SCRIPT_DIR}/slack_payload.json"

curl -X POST -H 'Content-type: application/json' --data "@${SCRIPT_DIR}/slack_payload.json" "${SLACK_WEBHOOK}"
