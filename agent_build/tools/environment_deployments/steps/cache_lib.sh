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

# This is a primitive caching library that can be used to save or reuse some intermediate results by some
# "Deployment Steps". See more in class "ShellScriptDeploymentStep" in the "agent_build/tools/environment_deployments/deployments.py"
set -e

CACHE_DIR="$1"


if [ -n "$CACHE_DIR" ]; then
  if [ ! -d "$CACHE_DIR" ]; then
    mkdir -p "${CACHE_DIR}"
  fi
  echo "Use dir ${CACHE_DIR} as cache."
  use_cache=true
else
  use_cache=false
fi



# Function that restores data from cache if exists.
function restore_from_cache() {
  if ! $use_cache ; then
    echo "Cache disabled."
    return 0
  fi
  name=$1
  path=$2

  full_path="${CACHE_DIR}/${name}"


  if [ -d "${full_path}" ]; then
    echo "Directory ${name} in cache. Reuse it."
    mkdir -p "$(dirname "$path")"
    cp -a "${full_path}/." "${path}"

  else
    echo "Directory ${name} not in cache"
  fi
  if [ -f "${full_path}" ]; then
    echo "File ${name} in cache. Reuse it."
    mkdir -p "$(dirname "$path")"
    cp -a "${full_path}" "${path}"

  else
    echo "File ${name} not in cache"
  fi
}


# Function that saves data to cache if needed.
function save_to_cache() {
  name=$1
  path=$2

  if ! $use_cache ; then
    echo "Cache disabled"
    return 0
  fi

  full_path="${CACHE_DIR}/${name}"

  if [ -f "${path}" ]; then
    if [ ! -f "${full_path}" ]; then
      echo "File ${path} saved to cache"
      mkdir -p "$(dirname "$full_path")"
      cp -a "${path}" "${full_path}"
    else
      echo "File ${path} not saved to cache"
    fi
  else
    if [ ! -d "${full_path}" ]; then
      echo "Directory ${path} saved to cache"
      mkdir -p "$(dirname "$full_path")"
      cp -a "${path}/." "${full_path}"

    else
      echo "Directory ${path} not saved to cache"
    fi
  fi



}