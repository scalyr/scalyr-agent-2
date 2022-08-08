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

# Install build dependencies according to a current distribution type.
if [ "$DISTRO_NAME" = "debian" ]; then
#  # Workaround for weird build failure on Circle CI, see
#  # https://github.com/docker/buildx/issues/495#issuecomment-995503425 for details
#  ln -s /usr/bin/dpkg-split /usr/sbin/dpkg-split
#  ln -s /usr/bin/dpkg-deb /usr/sbin/dpkg-deb
#  ln -s /bin/rm /usr/sbin/rm
#  ln -s /bin/tar /usr/sbin/tar
  apt-get install -y build-essential

elif [ "$DISTRO_NAME" = "alpine" ]; then
   apk add --virtual build-dependencies \
    binutils \
    build-base \
    gcc \
    g++ \
    make \
    python3-dev \
    patchelf
else
  2>&1 echo "Unknown DISTRO_NAME=${DISRO_NAME}"
  exit 1
fi

