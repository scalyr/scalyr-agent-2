#!/bin/sh
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

set -e

REQUIREMENTS_FILES="agent_build/requirement-files"

# orjson is wheel is not available for armv7 + musl yet so we exclude it here. We can't exclude it
# with pip environment markers since they are not specific enough.
if [ "$TARGETVARIANT" = "v7" ] && [ "$DISTRO_NAME" = "alpine" ]; then
  sed -i '/^orjson/d' "${REQUIREMENTS_FILES}/main-requirements.txt"
fi


# Right now we don't support lz4 on server side yet so we don't include this dependency since it doesn't offer pre built
# wheel and it substantially slows down base image build
sed -i '/^lz4/d' "${REQUIREMENTS_FILES}/compression-requirements.txt"

# Install agent dependencies.
pip3 install --upgrade pip
pip3 --no-cache-dir install --root /tmp/dependencies -r "${REQUIREMENTS_FILES}/docker-image-requirements.txt"

# Install dependencies for the test version of the image.
pip3 install --root /tmp/test-image-dependencies coverage=="${COVERAGE_VERSION}"
