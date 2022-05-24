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

# This script is used during the build of the Agent base docker image and it installs Python libraries that are
# required by the agent.

set -e

if [ -z "$PYTHON_BASE_IMAGE_NAME" ]; then
  >&2 echo "The 'PYTHON_BASE_IMAGE_NAME' environment variable has to be defined."
  exit 1
fi

# orjson is wheel is not available for armv7 + musl yet so we exclude it here. We can't exclude it
# with pip environment markers since they are not specific enough.
if [ "$TARGETVARIANT" = "v7" ] && test "${PYTHON_BASE_IMAGE_NAME#*alpine}" != "$PYTHON_BASE_IMAGE_NAME"; then
  sed -i '/^orjson/d' agent_build/requirement-files/main-requirements.txt;
fi

# Right now we don't support lz4 on server side yet so we don't include this dependency since it doesn't offer pre built
# wheel and it substantially slows down base image build
sed -i '/^lz4/d' agent_build/requirement-files/compression-requirements.txt

# Workaround so we can use pre-built orjson wheel for musl. We need to pin pip to older version for
# manylinux2014 wheel format to work.
# See https://github.com/ijl/orjson/issues/8 for details.
# If we don't that and we include orjson and zstandard, we need rust chain and building the image
# will be very slow due to cross compilation in emulated environment (QEMU)
# TODO: Remove once orjson and zstandard musl wheel is available - https://github.com/pypa/auditwheel/issues/305#issuecomment-922251777
echo 'manylinux2014_compatible = True' > /usr/local/lib/python3.8/_manylinux.py

# Install agent dependencies.
pip3 install --upgrade pip
PATH="/root/.cargo/bin:${PATH}"
pip3 --no-cache-dir install --root /tmp/dependencies -r agent_build/requirement-files/docker-image-requirements.txt

# If that's a test build, then also install testing required libs.
if [ -n "$TESTING" ]; then
  pip3 --no-cache-dir install --root /tmp/dependencies coverage==4.5.4
fi
# Clean up files which were installed to use manylinux2014 workaround
rm /usr/local/lib/python3.8/_manylinux.py