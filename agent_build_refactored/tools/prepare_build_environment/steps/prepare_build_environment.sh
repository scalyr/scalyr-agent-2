set -e

tar -xvf "${BUILD_PYTHON}/python.tar.gz" -C /
cp -a "${BUILD_PYTHON_DEPENDENCIES}/agent_dependencies/." /


/usr/libexec/scalyr-agent-2-python3 -c "import bz2"
/usr/libexec/scalyr-agent-2-python3 -c "import zlib"
/usr/libexec/scalyr-agent-2-python3 -c "import ctypes"
/usr/libexec/scalyr-agent-2-python3 -c "import readline"
/usr/libexec/scalyr-agent-2-python3 -c "import uuid"
/usr/libexec/scalyr-agent-2-python3 -c "import lzma"
/usr/libexec/scalyr-agent-2-python3 -c "import dbm"


/usr/libexec/scalyr-agent-2-python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"

apt update
DEBIAN_FRONTEND=noninteractive apt install -y ruby rubygems
gem install fpm -v ${FPM_VERSION}