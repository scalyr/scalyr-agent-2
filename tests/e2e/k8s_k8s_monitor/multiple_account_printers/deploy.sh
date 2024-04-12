#! /bin/bash

function validate_var_exists() {
  VAR_NAME=$1
  if [ -z "${!VAR_NAME}" ]; then
      echo_with_date "$VAR_NAME is unset or set to the empty string"
      exit 1
  fi
}

function echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

validate_var_exists scalyr_api_key_write_team_2
validate_var_exists scalyr_api_key_write_team_3
validate_var_exists scalyr_api_key_write_team_4
validate_var_exists scalyr_api_key_write_team_5
validate_var_exists scalyr_api_key_write_team_6
validate_var_exists scalyr_api_key_write_team_7

DIR=$(dirname "$0")

helm install multiple-account-test $DIR/chart \
  --set scalyr_api_key_write_team_2=$scalyr_api_key_write_team_2,scalyr_api_key_write_team_3=$scalyr_api_key_write_team_3,scalyr_api_key_write_team_4=$scalyr_api_key_write_team_4,scalyr_api_key_write_team_5=$scalyr_api_key_write_team_5,scalyr_api_key_write_team_6=$scalyr_api_key_write_team_6,scalyr_api_key_write_team_7=$scalyr_api_key_write_team_7 \
  --wait
#  --dry-run \
#  --debug \



