# base image that creates all necessary dependencies for
# the scalyr-agent, and builds a tarball of the scalyr-agent
# from the source code of the main scalyr-agent-2 repository
# NOTE: multi-stage builds require Docker 17.05 or greater
FROM python:2.7-alpine3.9 as scalyr-dependencies
MAINTAINER Scalyr Inc <support@scalyr.com>

# install dev dependencies.
RUN apk --update add build-base python-dev gcc git bash
RUN mkdir -p /tmp/scalyr/src

# install python dependencies
RUN pip --no-cache-dir install --root /tmp/dependencies ujson yappi

# clone the source from the master branch of the main scalyr repository
WORKDIR /tmp/scalyr
RUN git init
RUN git config --local user.name "Scalyr" && git config --local user.email support@scalyr.com
RUN git clone git://github.com/scalyr/scalyr-agent-2.git ./src

# package up the source in a k8s compatible tarball
WORKDIR ./src
RUN python build_package.py --no-versioned-file-name k8s_builder
RUN ./scalyr-k8s-agent --extract-packages

# extract the tarball in a well-known location
RUN mkdir -p /tmp/scalyr/install
RUN tar --no-same-owner -C /tmp/scalyr/install -zxf /tmp/scalyr/src/scalyr-k8s-agent.tar.gz

# main image - copies dependencies and the scalyr-agent from scalyr-dependencies
FROM python:2.7-alpine3.9 as scalyr
MAINTAINER Scalyr Inc <support@scalyr.com>

COPY --from=scalyr-dependencies  /tmp/dependencies/ /
COPY --from=scalyr-dependencies  /tmp/scalyr/install/ /

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]
