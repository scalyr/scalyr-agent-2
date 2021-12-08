#!/bin/bash
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

# This is a " runner" script that serves as an entry point for the scripts that are specified in the Deployment Steps
# with shell scripts.
# See more in class "ShellScriptDeploymentStep" in the "agent_build/tools/environment_deployments/deployments.py"
#
# The runner script accepts the path to the script to run as a first argument. The target script is called by using
# 'source' command.
# The runner script also accepts the optional cache directory as a second argument. If the cache directory is specified,
# then it enables primitive caching mechanism that can be used by target scripts to cache their results in that
# directory.

STEP_SCRIPT_PATH="$1"
CACHE_DIR="$2"

set -e

PARENT_DIR="$(dirname "$0")"
SOURCE_ROOT=$(dirname "$(dirname "$(dirname "$(dirname "$PARENT_DIR")")")")

# Simple log function to make log message more noticeable and distinguishable form each other.
# Accepts first optional arguments: '-nb' and '-ne'
# -nb: The normal message starts with "# " prefix. this option removes it so it can be concatenated with a previous
#   log message.
# -ne: Do not add newline at the end of the message.
function log() {
  other_args="$@"
  new_message_prefix=""
  new_line_option=""
  if [[ "$1" == "-nb" ]]; then
    other_args="${@:2}"
  else
    new_message_prefix="# "
  fi

  if [[ "$1" == "-ne" ]];then
    new_line_option="-n"
    other_args="${@:2}"
  fi

  >&2 echo "$new_line_option"  "$new_message_prefix" "${other_args[@]}"
}

# Function that runs given command from arguments in 'sh'
function sh_c() {
  echo "sh -c '${*}'"
  sh -c "${*}" > /dev/null
}

# The same function to run the command but with preserved standard output from the given command,
# so the output can be redirected.
function sh_cs() {
  sh -c "${*}"
}

log "=========== Run Deployment Step Script'$(basename "$STEP_SCRIPT_PATH")' ==========="

# Check if the cache directory is specified. If it doesn't, then the caching has to be disabled.
if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    mkdir -p "${CACHE_DIR}"
  fi
  log "Use directory ${CACHE_DIR} as cache."
  use_cache=true
else
  use_cache=false
fi



# Function that restores data from cache if exists.
function restore_from_cache() {
  if ! $use_cache ; then
    log "Cache disabled."
    return 0
  fi
  cache_key=$1
  path=$2

  full_cache_path="${CACHE_DIR}/${cache_key}"

  log -ne "Restore path '${path}' from cache key '${cache_key}'...  "

  if [ -d "${full_cache_path}" ]; then
    log -nb "found (directory)"
    mkdir -p "$(dirname "$path")"
    cp -a "${full_cache_path}/." "${path}"
  elif [ -f "${full_cache_path}" ]; then
    log -nb "found (file)"
    mkdir -p "$(dirname "$path")"
    cp -a "${full_cache_path}" "${path}"
  else
    log -nb "not found."
  fi
}


# Function that saves data to cache if needed.
function save_to_cache() {
  cache_key=$1
  path=$2

  if ! $use_cache ; then
    log "Cache disabled"
    return 0
  fi

  full_cache_path="${CACHE_DIR}/${cache_key}"

  if [ -f "${path}" ]; then
    if [ ! -f "${full_cache_path}" ]; then
      mkdir -p "$(dirname "$full_cache_path")"
      log "File ${path} saved to cache directory: '${full_cache_path}'"
      cp -a "${path}" "${full_cache_path}"
    else
      log "File ${path} is already in the cache, and there's no need to save it."
    fi
  else
    if [ ! -d "${full_cache_path}" ]; then
      mkdir -p "$(dirname "$full_cache_path")"
      cp -a "${path}/." "${full_cache_path}"
      log "Directory ${path} saved to cache directory: '${full_cache_path}'"
    else
      log "Directory ${path} is already in the cache, and there's no need to save it."
    fi
  fi
}

# Export useful variables, so they can be used by the script.
export SOURCE_ROOT

# Run the script.
source "${STEP_SCRIPT_PATH}"

log "=========== The Deployment Step Script '$(basename "$STEP_SCRIPT_PATH")' is successfully ended ==========="
