#!/usr/bin/env bash

echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

function validate_var_exists() {
  VAR_NAME=$1
  eval VALUE=\$$VAR_NAME
  if [ -z "${VALUE}" ]; then
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

# See tests/e2e/k8s_k8s_monitor/multiple_account_printers.yaml:16 for the following annotations:
# log.config.scalyr.com/teams.1.secret: "scalyr-api-key-team-2"
# log.config.scalyr.com/cont1.teams.2.secret: "scalyr-api-key-team-3"
# log.config.scalyr.com/cont2.teams.2.secret: "scalyr-api-key-team-3"
# log.config.scalyr.com/cont2.teams.3.secret: "scalyr-api-key-team-4"

# Container 1 log is ingested with the scalyr-api-key-team-3 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont1
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont1

# Container 2 log is ingested with the scalyr-api-key-team-3 and scalyr-api-key-team-4 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont2
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont2
assert_multiple_account_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont2

# Container 3 log is ingested with the scalyr-api-key-team-2 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont3
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont3

export STATUS=`kubectl exec --namespace scalyr ${SCALYR_AGENT_POD_NAME} -- scalyr-agent-2 status -v --format json`
export WORKER_ID_DEFAULT="default"
export WORKER_ID_API_KEY_2=`echo $STATUS | jq -r -c '.copying_manager_status.workers[] | select (.sessions[].log_processors[].log_path | strings | test("cont3")) | .worker_id'`
export WORKER_ID_API_KEY_3=`echo $STATUS | jq -r -c '.copying_manager_status.workers[] | select(.sessions[].log_processors[].log_path | test("cont2")) | select (.sessions[].log_processors | length == 2) | .worker_id'`
export WORKER_ID_API_KEY_4=`echo $STATUS | jq -r -c '.copying_manager_status.workers[] | select(.sessions[].log_processors[].log_path | test("cont2")) | select (.sessions[].log_processors | length == 1) | .worker_id'`

function assert_worker_files_count() {
  API_KEY_NAME=$1; shift;
  WORKER_ID=$1; shift;
  EXPECTED_COUNT=$1;

  echo_with_date "Fetching agent status"
  echo_with_date "Checking worker $WORKER_ID (using $API_KEY_NAME) files count"

  STATUS=`kubectl exec --namespace scalyr ${SCALYR_AGENT_POD_NAME} -- scalyr-agent-2 status -v --format json`

  COUNT=`echo $STATUS | jq -c ".copying_manager_status.workers[] | select (.worker_id==\"$WORKER_ID\") | .sessions[0].log_processors | length"`

  if [ "$COUNT" != "$EXPECTED_COUNT" ]; then
    echo $STATUS | jq -c ".copying_manager_status.workers[] | select (.worker_id==\"$WORKER_ID\")"
    echo_with_date "FAIL: Expected $EXPECTED_COUNT files, got $COUNT. See worker status json above."
    exit 1
  fi
}


assert_worker_files_count scalyr-api-key-2 $WORKER_ID_API_KEY_2 1
assert_worker_files_count scalyr-api-key-3 $WORKER_ID_API_KEY_3 2
assert_worker_files_count scalyr-api-key-4 $WORKER_ID_API_KEY_4 1

echo
echo_with_date "Changing the multiple-account-printer POD team api key annotations and observing the logs (I)"
echo

export MULTIPLE_ACCOUNT_PRINTER_POD_NAME=$(kubectl get pod --namespace=default --selector=app=multiple-account-printer -o jsonpath="{.items[0].metadata.name}")

echo_with_date "Current Pod description:"
kubectl describe pod ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME}
echo

kubectl annotate --overwrite pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/cont3.teams.1.secret="scalyr-api-key-team-3"
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/cont2.teams.2.secret-
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/cont2.teams.1.secret-
kubectl annotate pods ${MULTIPLE_ACCOUNT_PRINTER_POD_NAME} log.config.scalyr.com/cont1.teams.2.secret-

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

# Pod annotations are changed to:
# log.config.scalyr.com/teams.1.secret: "scalyr-api-key-team-2"
# log.config.scalyr.com/cont3.teams.1.secret: "scalyr-api-key-team-3"

# Container 1 log is ingested with the scalyr-api-key-team-3 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont1
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont1
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont1

# Container 2 log is ingested with the scalyr-api-key-team-2 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont2
assert_multiple_account_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont2
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont2

# Container 3 log is ingested with the scalyr-api-key-team-3 only
assert_multiple_account_not_ingested ${ACCOUNT_NAME} ${scalyr_api_key_team} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_2} ${scalyr_api_key_team_2} cont3
assert_multiple_account_ingested ${ACCOUNT_NAME_3} ${scalyr_api_key_team_3} cont3
assert_multiple_account_not_ingested ${ACCOUNT_NAME_4} ${scalyr_api_key_team_4} cont3


assert_worker_files_count scalyr-api-key-2 $WORKER_ID_API_KEY_2 2
assert_worker_files_count scalyr-api-key-3 $WORKER_ID_API_KEY_3 1
assert_worker_files_count scalyr-api-key-4 $WORKER_ID_API_KEY_4 0

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

assert_worker_files_count scalyr-api-key-2 $WORKER_ID_API_KEY_2 0
assert_worker_files_count scalyr-api-key-3 $WORKER_ID_API_KEY_3 1
assert_worker_files_count scalyr-api-key-4 $WORKER_ID_API_KEY_4 0

echo