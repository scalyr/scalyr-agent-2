set -e

if [ "$PYTHON_BASE_IMAGE_TYPE" = "debian" ]; then
  apt-get update && apt-get install -y build-essential
else
  apk update && apk add --virtual build-dependencies \
    binutils \
    build-base \
    gcc \
    g++ \
    make \
    python3-dev \
    patchelf
fi