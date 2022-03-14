#!/usr/bin/env bash
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

# This script is used by "ShellScriptDeploymentStep"
# (See more in class "ShellScriptDeploymentStep" in the "agent_build/tools/environment_deployments/deployments.py"

# This helper library that is used in the deployment step that build base image for agent docker images.
# This file is sourced by one of the actual shell scripts that has to build the base image.


# The builder of the agent docker images have to use this base image in order to create a final image.
#    Since it's not a trivial task to "transfer" a multi-platform image from one place to another, the image is
#    pushed to a local registry in the container, and the root of that registry is transferred instead.
#
# Registry's root in /var/lib/registry is exposed to the host by using docker's mount feature and saved in the
#    deployment's output directory. This final image builder then spins up another local registry container and
#    mounts root of the saved registry. Now builder can refer to this local registry in order to get the base image.


set -e

TO_BUILD_PLATFORMS=${TO_BUILD_PLATFORMS:-"linux/amd64,linux/arm64,linux/arm/v7"}
IFS=', ' read -r -a TO_BUILD_PLATFORMS_ARRAY <<< "${TO_BUILD_PLATFORMS}"

PLATFORMS_DOCKER_BUILX_ARGS=""
for PLATFORM in "${TO_BUILD_PLATFORMS_ARRAY[@]}"; do
    PLATFORMS_DOCKER_BUILX_ARGS="${PLATFORMS_DOCKER_BUILX_ARGS} --platform ${PLATFORM}"
done

log "Building image for the following platforms: ${TO_BUILD_PLATFORMS}"

# The directory with registry's data root
registry_output_path="$STEP_OUTPUT_PATH/output_registry"

# Clear the registry data root path.
rm -rf "$registry_output_path"

# Check if registry data root already exists in cache.
restore_from_cache output_registry "$registry_output_path"

if [ -d "$registry_output_path" ]; then
  log "Registry data root is found in cache. Skip building of the base image and reuse it from found registry."
  exit 0
fi

# Create temporary registry folder, it will be renamed to the valid name at the very end, so we won't use
# "broken" directory if it fails in the middle.
tmp_registry_output_path="$STEP_OUTPUT_PATH/~output_registry"

# Remove temp registry folder from previous run.
if [ -d "$tmp_registry_output_path" ]; then
  rm -r "$tmp_registry_output_path"
fi

log "Registry data root is not found in cache, build image from scratch"
sh_cs mkdir -p "$tmp_registry_output_path"

container_name="agent_base_image_registry_step"

kill_registry_container() {
  sh_cs docker rm -f "$container_name"
}

trap kill_registry_container EXIT

# Kill registry container from the previous run, is exists.
kill_registry_container

log "Spin up local registry in container"
sh_cs docker run -d --rm -p 5005:5000 -v "$tmp_registry_output_path:/var/lib/registry" --name "$container_name" registry:2

buildx_version=$(docker buildx version)
log "Using buildx version: ${buildx_version}"

buildx_builder_name="agent_image_buildx_builder"

if ! sh_cs docker buildx ls | grep $buildx_builder_name ; then
  log "Create new  buildx builder instance."
  sh_cs docker \
    buildx \
    create \
    --driver-opt=network=host \
    --name \
    "$buildx_builder_name"
fi

log "Use buildx builder instance."
sh_cs docker buildx use "$buildx_builder_name"


# Build all needed base images.
build_all_base_images() {
  # The argument is a tag suffix of the Python's image on dockerhub image.
  # According to that suffix, the appropriate python image will be used.
  # For example, for base image that is based on debian, the suffix is 'slim', so the builder will use "python:slim",
  # or 'alpine, so builder will use 'python:alpine'
  base_image_tag_suffix=$1

  log "Build base image with Python:$base_image_tag_suffix"

  build_base_image() {
    use_test_version=$1

    coverage_arg=""
    tag_suffix=""
    if $use_test_version ; then
      coverage_arg="--build-arg COVERAGE_VERSION=4.5.4"
      tag_suffix="-testing"
    fi

    # shellcheck disable=SC2086 # Intended splitting of coverage_arg
    sh_cs docker \
      buildx build \
      -t "localhost:5005/agent_base_image:$base_image_tag_suffix$tag_suffix" \
      -f "$SOURCE_ROOT/agent_build/docker/Dockerfile.base" \
      --push \
      --build-arg "BASE_IMAGE_SUFFIX=$base_image_tag_suffix" \
      $coverage_arg \
      "${PLATFORMS_DOCKER_BUILX_ARGS}" \
      "$SOURCE_ROOT"

  }
  # Build images
  # test version
  build_base_image true

  # prod version
  build_base_image false

  # Everything is successful, rename temp registry folder to normal.
  mv "$tmp_registry_output_path" "$registry_output_path"

  log "Save registry's data root to cache to reuse it in future."
  save_to_cache output_registry "$registry_output_path"
}
