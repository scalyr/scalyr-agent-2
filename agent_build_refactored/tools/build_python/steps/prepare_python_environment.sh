set -e

source ~/.bashrc

tar -xvf "${BUILD_PYTHON}/python.tar.gz" -C /

mkdir /tmp/ddd
tar -xvf "${BUILD_PYTHON}/all-dependencies.tar.gz" -C /

echo "GGGGGGGGGGGG"


ln -s /usr/libexec/scalyr-agent-2-python3 /usr/bin/python3

python3 --version




#/usr/libexec/scalyr-agent-2-python3 -c "import bz2"
#/usr/libexec/scalyr-agent-2-python3 -c "import zlib"
#/usr/libexec/scalyr-agent-2-python3 -c "import ctypes"
#/usr/libexec/scalyr-agent-2-python3 -c "import readline"
#/usr/libexec/scalyr-agent-2-python3 -c "import uuid"
#/usr/libexec/scalyr-agent-2-python3 -c "import lzma"
#/usr/libexec/scalyr-agent-2-python3 -c "import dbm"
#
#ls /usr/include/scalyr-agent-2-dependencies/python3.10
#CFLAGS="-I/usr/include/scalyr-agent-2-dependencies/python3.10" \
#  /usr/libexec/scalyr-agent-2-python3 -m pip install -r "${SOURCE_ROOT}/dev-requirements.txt"

python3 -c "import bz2"
python3 -c "import zlib"
python3 -c "import ctypes"
python3 -c "import readline"
python3 -c "import uuid"
python3 -c "import lzma"
python3 -c "import dbm"