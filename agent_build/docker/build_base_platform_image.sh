#!/usr/env python3
# Copyright 2014-2022 Scalyr Inc.
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

# This script is used to build base image for the agent images and used by a special runner step.
# It produces tarball with base agent image for a particular platform/architecture.

# It expects the next environment variables.
#    PYTHON_BASE_IMAGE: Name of the base image (e.g. python:slim, python:alpine)
#    DISTRO_NAME: name of the base distribution (e.g. debian, alpine)
#    RESULT_IMAGE_TARBALL_NAME: Name of the result image tarball.
#    PLATFORM: Architecture of the result platform.
#    COVERAGE_VERSION: Version coverage to install for test version of the image.


# Prepare buildx builder.
buildx_version=$(docker buildx version)
log "Using buildx version: ${buildx_version}"

buildx_builder_name="agent_image_buildx_builder"

if ! sh_cs docker buildx ls | grep $buildx_builder_name ; then
  log "Create new  buildx builder instance."
  docker buildx create \
    --driver-opt=network=host \
    --name "$buildx_builder_name"
fi

log "Use buildx builder instance."
docker buildx use "$buildx_builder_name"

docker buildx build \
  -f "${SOURCE_ROOT}/agent_build/docker/base.Dockerfile" \
  --platform "${PLATFORM}" \
  --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
  --build-arg "DISTRO_NAME=${DISTRO_NAME}" \
  --build-arg "COVERAGE_VERSION=${COVERAGE_VERSION}" \
  --output "type=oci,dest=${STEP_OUTPUT_PATH}/${RESULT_IMAGE_TARBALL_NAME}" \
  ${SOURCE_ROOT}