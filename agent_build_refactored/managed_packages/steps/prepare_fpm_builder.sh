set -e

source ~/.bashrc
tar -xvf "${BUILD_PYTHON}/python.tar.gz" -C /
tar -xvf "${BUILD_PYTHON}/all-dependencies.tar.gz" -C /
ln -s /usr/libexec/scalyr-agent-2-python3 /usr/bin/python3

apt update
DEBIAN_FRONTEND=noninteractive apt install -y ruby rubygems build-essential
gem install fpm -v ${FPM_VERSION}

