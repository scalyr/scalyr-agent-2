#!/bin/bash
# Copyright 2024 Scalyr Inc.
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

# Utility script which calls scalyr query tools and exists with non in case the provided query
# returns no results after maximum number of retry attempts has been reached. We perform multiple
# retries to make the build process more robust and less flakey and to account for delayed
# ingestion for any reason.


echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

function validate_var_exists() {
  VAR_NAME=$1
  if [ -z "${!VAR_NAME}" ]; then
      echo_with_date "$VAR_NAME is unset or set to the empty string"
      exit 1
  fi
}

validate_var_exists scalyr_api_key_team
validate_var_exists scalyr_api_key_team_2
validate_var_exists scalyr_api_key_team_3
validate_var_exists scalyr_api_key_team_4
validate_var_exists SCALYR_AGENT_POD_NAME
validate_var_exists ACCOUNT_NAME
validate_var_exists ACCOUNT_NAME_2
validate_var_exists ACCOUNT_NAME_3
validate_var_exists ACCOUNT_NAME_4


function assert_multiple_account_not_ingested() {
  ACCOUNT_NAME=$1; shift;
  scalyr_readlog_token=$1; shift;
  CONT_NAME=$1; shift;
  echo_with_date "Expecting to find no logs for account $ACCOUNT_NAME and container $CONT_NAME"
  scalyr_readlog_token=${scalyr_readlog_token} RETRY_ATTEMPTS=1 ./scripts/cicd/scalyr-query.sh '$serverHost="'${SCALYR_AGENT_POD_NAME}'" app="multiple-account-printer" "MULTIPLE_ACCOUNT_TEST_CONTAINER_NAME:'$CONT_NAME'"'  && echo -e "\xE2\x9D\x8C FAIL: Some lines were found." && exit 1 || echo -e "\xE2\x9C\x94 PASS: Search failed as expected - no lines found."
}

function assert_multiple_account_ingested() {
  ACCOUNT_NAME=$1; shift;
  scalyr_readlog_token=$1; shift;
  CONT_NAME=$1; shift;
  echo_with_date "Expecting to find some logs for account $ACCOUNT_NAME and container $CONT_NAME"
  scalyr_readlog_token=${scalyr_readlog_token} RETRY_ATTEMPTS=1 ./scripts/cicd/scalyr-query.sh '$serverHost="'${SCALYR_AGENT_POD_NAME}'" app="multiple-account-printer" "MULTIPLE_ACCOUNT_TEST_CONTAINER_NAME:'$CONT_NAME'"'
}

# workload-pod-1 annotations:
#log.config.scalyr.com/teams.1.secret: "scalyr-api-key-team-3"
#log.config.scalyr.com/teams.5.secret: "scalyr-api-key-team-4"
#log.config.scalyr.com/workload-pod-1-container-1.teams.1.secret: "scalyr-api-key-team-5"
#log.config.scalyr.com/workload-pod-1-container-2.teams.1.secret: "scalyr-api-key-team-6"
#log.config.scalyr.com/workload-pod-1-container-2.teams.2.secret: "scalyr-api-key-team-7"

#| Container Name | API keys used to ingest logs                                         | Note                        |
#| -------------- |----------------------------------------------------------------------|-----------------------------|
#| workload-pod-1-container-1 | SCALYR_API_KEY_WRITE_TEAM_4                              | Container specific api keys |
#| workload-pod-1-container-2 | SCALYR_API_KEY_WRITE_TEAM_5, SCALYR_API_KEY_WRITE_TEAM_6 | Container specific api keys |
#| workload-pod-1-container-3 | SCALYR_API_KEY_WRITE_TEAM_3, SCALYR_API_KEY_WRITE_TEAM_4 | Pod default api keys        |
#| workload-pod-2-container-1 | SCALYR_API_KEY_WRITE_TEAM_2                              | Namespace default api key   |
#| workload-pod-3-container-1 | SCALYR_API_KEY_WRITE_TEAM_1                              | Agent default api key       |

# workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-1

# workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-2
assert_multiple_account_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-2
assert_multiple_account_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-2

# workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-3
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-3
assert_multiple_account_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-3

# workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-2-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-2-container-1

# workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-3-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-3-container-1


echo
echo_with_date "Changing the multiple-account-printer POD team api key annotations and observing the logs (I)"
echo

export MULTIPLE_ACCOUNT_PRINTER_POD_NAME=workload-pod-1

echo_with_date "Current Pod description:"
kubectl describe pod ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME}
echo

kubectl annotate --overwrite pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/workload-pod-1-container-3.teams.1.secret="scalyr-api-key-team-3"
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/workload-pod-1-container-1.teams.1.secret-
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/workload-pod-1-container-2.teams.1.secret-
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/workload-pod-1-container-2.teams.2.secret-

echo
echo_with_date "New Pod description:"
kubectl describe pod ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME}
echo

echo_with_date "Waiting for the agent to pick up the changes and ingesting for a minute"
# Give agent some time to pick up the annotation change (by default we poll every 30 seconds
# for pod metadata changes, but we use lower value for the tests)
# TODO Keep checking logs to avoid waiting for 30s
sleep 90

export START_TIME="1m"

# workload-pod-1 annotations:
#log.config.scalyr.com/teams.1.secret: "scalyr-api-key-team-3"
#log.config.scalyr.com/teams.5.secret: "scalyr-api-key-team-4"
#log.config.scalyr.com/cont3.teams.1.secret: "scalyr-api-key-team-3"

#| Container Name | API keys used to ingest logs                                         | Note                        |
#| -------------- |----------------------------------------------------------------------|-----------------------------|
#| workload-pod-1-container-1 | SCALYR_API_KEY_WRITE_TEAM_2                              | Namespace default api key   |
#| workload-pod-1-container-2 | SCALYR_API_KEY_WRITE_TEAM_2                              | Namespace default api key   |
#| workload-pod-1-container-3 | SCALYR_API_KEY_WRITE_TEAM_3                              | Pod default api keys        |
#| workload-pod-2-container-1 | SCALYR_API_KEY_WRITE_TEAM_2                              | Namespace default api key   |
#| workload-pod-3-container-1 | SCALYR_API_KEY_WRITE_TEAM_1                              | Agent default api key       |

# workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-1

# workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-2
assert_multiple_account_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-2
assert_multiple_account_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-2

# workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-1-container-3
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-1-container-3
assert_multiple_account_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-1-container-3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-1-container-3

# workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-2-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-2-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-2-container-1

# workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} workload-pod-3-container-1
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_5} ${scalyr_api_key_team_5} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_6} ${scalyr_api_key_team_6} workload-pod-3-container-1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_7} ${scalyr_api_key_team_7} workload-pod-3-container-1


echo
echo_with_date "Changing the multiple-account-printer POD team api key annotations and observing the logs (II)"
echo
echo_with_date "Current Pod description:"
kubectl describe pod ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME}
echo

kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/teams.1.secret-

echo
echo_with_date "New Pod description:"
kubectl describe pod ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME}
echo

echo_with_date "Waiting for the agent to pick up the changes and ingesting for a minute"
# Give agent some time to pick up the annotation change (by default we poll every 30 seconds
# for pod metadata changes, but we use lower value for the tests)
sleep 90

# Pod annotations are changed to:
# log.config.scalyr.com/cont3.teams.1.secret: "scalyr-api-key-team-3"

# Container 1 log is ingested with the scalyr-api-key-team only
assert_multiple_account_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont1

# Container 2 log is ingested with the scalyr-api-key-team only
assert_multiple_account_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont2

# Container 3 log is ingested with the scalyr-api-key-team-3 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont3
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont3

echo