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

# This script is used during the build of the Agent base docker image and it installs all required packages, such gcc and others
# which are used to build a final image.

set -e

if [ -z "$PYTHON_BASE_IMAGE_NAME" ]; then
  >&2 echo "The 'PYTHON_BASE_IMAGE_NAME' environment variable has to be defined."
  exit 1
fi

echo "${PYTHON_BASE_IMAGE_NAME#*slim}"

if test "${PYTHON_BASE_IMAGE_NAME#*slim}" != "$PYTHON_BASE_IMAGE_NAME"; then
  # Workaround for weird build failure on Circle CI, see
  # https://github.com/docker/buildx/issues/495#issuecomment-995503425 for details
  ln -s /usr/bin/dpkg-split /usr/sbin/dpkg-split
  ln -s /usr/bin/dpkg-deb /usr/sbin/dpkg-deb
  ln -s /bin/rm /usr/sbin/rm
  ln -s /bin/tar /usr/sbin/tar
  apt-get update && apt-get install -y build-essential git tar curl
else
  apk update && apk add --virtual build-dependencies \
    binutils \
    build-base \
    gcc \
    g++ \
    make \
    python3-dev \
    patchelf \
    git \
    tar \
    curl
fi