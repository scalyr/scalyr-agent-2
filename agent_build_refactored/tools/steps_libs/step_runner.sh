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

#
# The runner script accepts the path to the script to run as a first argument. The target script is called by using
# 'source' command.
# The runner script also accepts the optional cache directory as a second argument. If the cache directory is specified,
# then it enables primitive caching mechanism that can be used by target scripts to cache their results in that
# directory.

STEP_SCRIPT_PATH="$1"
CACHE_DIR="$2"
STEP_OUTPUT_PATH="$3"
SCRIPT_TYPE="$4"

set -e

# The root of the agent source. This variable has to be used in order to access agent files.
SOURCE_ROOT=$(pwd)


in_docker_prefix=""
# If the special 'IN_DOCKER' variable is passed, then add additional prefix to all log messages.
if [ -n "$IN_DOCKER" ]; then
  in_docker_prefix="[IN_DOCKER]"
fi

# Simple log function to make log message more noticeable and distinguishable form each other.
# Accepts first optional arguments: '-nb' and '-ne'
# -nb: The normal message starts with "# " prefix. this option removes it so it can be concatenated with a previous
#   log message.
# -ne: Do not add newline at the end of the message.
log() {
  >&2 echo " # ${in_docker_prefix} ${*}"
}

# Function that runs given command from arguments in 'sh'
sh_c() {
  >&2 echo " ${in_docker_prefix} sh -c '${*}'"
  sh -c "${*}" > /dev/null
}

# The same function to run the command but with preserved standard output from the given command,
# so the output can be redirected.
sh_cs() {
  >&2 echo "${in_docker_prefix} sh -c '${*}'"
  sh -c "${*}"
}

log "=========== Execute Runner Step Script'$(basename "$STEP_SCRIPT_PATH")' ==========="

log "SOURCE_ROOT: ${SOURCE_ROOT}"
log "STEP_OUTPUT_PATH: ${STEP_OUTPUT_PATH}"
log "STEP_CACHE_DIR: ${CACHE_DIR}"


# Function that restores data from cache if exists.
restore_from_cache() {
  if [ -z "$IN_CICD" ]; then
    log "Cache disabled."
    return 0
  fi
  cache_key=$1
  path=$2

  full_cache_path="${CACHE_DIR}/${cache_key}"

  log "Restore path '${path}' from cache key '${cache_key}'...  "

  if [ -d "${full_cache_path}" ]; then
    log "Cache found (directory)"
    mkdir -p "$(dirname "$path")"
    cp -a "${full_cache_path}/." "${path}"
  elif [ -f "${full_cache_path}" ]; then
    log "Cache found (file)"
    mkdir -p "$(dirname "$path")"
    cp -a "${full_cache_path}" "${path}"
  else
    log "Cache not found."
  fi
}


# Function that saves data to cache if needed.
save_to_cache() {
  cache_key=$1
  path=$2

  if [ -z "$IN_CICD" ]; then
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
export STEP_OUTPUT_PATH

# Run the script.
if [ "${SCRIPT_TYPE}" = "shell" ]; then
    # shellcheck disable=SC1090
  . "${STEP_SCRIPT_PATH}"
elif [ "${SCRIPT_TYPE}" = "python" ]; then
  PYTHONPATH="${SOURCE_ROOT}:${PYTHONPATH}" ${STEP_SCRIPT_PATH}
else
  ${STEP_SCRIPT_PATH}
fi

log "=========== The Runner Step Script '$(basename "$STEP_SCRIPT_PATH")' is successfully ended ==========="
