set -e

if [ "$PYTHON_BASE_IMAGE_TYPE" = "debian" ]; then
  # Workaround for weird build failure on Circle CI, see
  # https://github.com/docker/buildx/issues/495#issuecomment-995503425 for details
  ln -s /usr/bin/dpkg-split /usr/sbin/dpkg-split
  ln -s /usr/bin/dpkg-deb /usr/sbin/dpkg-deb
  ln -s /bin/rm /usr/sbin/rm
  ln -s /bin/tar /usr/sbin/tar

  apt-get update && apt-get install -y git tar curl
else
  apk update && apk add --virtual curl git
fi