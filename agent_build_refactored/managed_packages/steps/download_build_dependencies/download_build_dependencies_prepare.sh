set -e

apt update

DEBIAN_FRONTEND=noninteractive apt install -y git curl gnupg gnupg2 xz-utils
