#!/usr/bin/env bash

set -e

yum install -y tar wget perl
yum groupinstall -y 'Development Tools'

# Build and install openssl, since python 3.8+ requires newer version than centos 7 can provide.
wget https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_1_1_1k.tar.gz -O /tmp/openssl-build.tar.gz

mkdir -p /tmp/openssl-build

tar -xf /tmp/openssl-build.tar.gz -C /tmp/openssl-build --strip-components 1

pushd /tmp/openssl-build || exit 1

/tmp/openssl-build/config --prefix="/usr/local" --openssldir="/usr/local" shared

make -j2

make install

pushd /

echo "/usr/local/lib" >> /etc/ld.so.conf.d/local.conf
echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
ldconfig


# Build and install python
yum install -y git gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel \
   tk-devel libffi-devel xz-devel

git clone https://github.com/pyenv/pyenv.git ~/.pyenv

PYTHON_CONFIGURE_OPTS=--enable-shared ~/.pyenv/plugins/python-build/bin/python-build 3.8.10 /usr/local

ldconfig

git clone https://github.com/rbenv/rbenv.git ~/.rbenv

git clone https://github.com/rbenv/ruby-build.git ~/.rbenv/plugins/ruby-build

# Build and install ruby and fpm package.
~/.rbenv/plugins/ruby-build/bin/ruby-build 2.7.3 /usr/local

ldconfig

gem install --no-document fpm -v 1.12.0

gem cleanup

# Install pyinstaller and other possible requirements.
python3 -m pip install -r /scalyr-agent-2/agent_build/frozen-binary-builder-requirements.txt
python3 -m pip install -r /scalyr-agent-2/agent_build/requirements.txt
python3 -m pip install -r /scalyr-agent-2/agent_build/monitors_requirements.txt

yum install -y git rpm-build

yum clean all

rm -rf /tmp/*

rm -rf ~/.pyenv ~/.rbenv
ldconfig

