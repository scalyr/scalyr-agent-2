FROM centos:7 as build

RUN yum install -y tar wget perl
RUN yum groupinstall -y 'Development Tools'

# Build and install openssl, since python 3.8+ requires newer version than centos 7 can provide.
RUN wget https://github.com/openssl/openssl/archive/refs/tags/OpenSSL_1_1_1k.tar.gz -O /tmp/openssl-build.tar.gz

RUN mkdir -p /tmp/openssl-build

RUN tar -xf /tmp/openssl-build.tar.gz -C /tmp/openssl-build --strip-components 1

WORKDIR /tmp/openssl-build

RUN /tmp/openssl-build/config --prefix="/usr/local" --openssldir="/usr/local" shared

RUN make -j2

RUN make install

WORKDIR /

RUN echo "/usr/local/lib" >> /etc/ld.so.conf.d/local.conf
RUN echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
RUN ldconfig


# Build and install python
RUN yum install -y git gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel \
   tk-devel libffi-devel xz-devel

RUN git clone https://github.com/pyenv/pyenv.git ~/.pyenv

RUN PYTHON_CONFIGURE_OPTS=--enable-shared ~/.pyenv/plugins/python-build/bin/python-build 3.8.10 /usr/local

RUN ldconfig

RUN git clone https://github.com/rbenv/rbenv.git ~/.rbenv

RUN git clone https://github.com/rbenv/ruby-build.git ~/.rbenv/plugins/ruby-build

# Build and install ruby and fpm package.
RUN ~/.rbenv/plugins/ruby-build/bin/ruby-build 2.7.3 /usr/local

RUN ldconfig

RUN gem install --no-document fpm -v 1.12.0

RUN gem cleanup

# Install pyinstaller and other possible requirements.
ADD ./agent_build/requirements.txt /scalyr-agent-2/agent_build/requirements.txt
RUN python3 -m pip install -r /scalyr-agent-2/agent_build/requirements.txt
RUN mkdir -p /tmp/build/tarball_wheels
RUN python3 -m pip download -d /tmp/build/tarball_wheels -r /scalyr-agent-2/agent_build/requirements.txt


# Install agent's requirements.
ADD agent_build/docker_images/frozen_binary_and_fpm_builder/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

FROM centos:7

# copy only installed things to a new stage to reduc the image size.
COPY --from=build /usr/local /usr/local
COPY --from=build /etc/ld.so.conf.d/local.conf /etc/ld.so.conf.d/local.conf
COPY --from=build /tmp/build/tarball_wheels /tmp/build/tarball_wheels

RUN yum install -y git rpm-build

RUN ldconfig

