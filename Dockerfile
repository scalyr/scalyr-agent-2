FROM python:2.7-slim as build

MAINTAINER Scalyr Inc <support@scalyr.com>

RUN apt-get update && apt-get install -y build-essential

# install python dependencies
ADD ./docker/requirements.txt /tmp/requirements.txt
RUN pip --no-cache-dir install --root /tmp/dependencies -r /tmp/requirements.txt


ADD . /scalyr-agent-2
WORKDIR /tmp/build

# build container tarball.
RUN python /scalyr-agent-2/build_package.py docker_json_builder --only-container-tarball

RUN mkdir /tmp/build/source
RUN tar -xf scalyr-docker-agent.tar.gz -C /tmp/build/source

FROM python:2.7-slim

COPY --from=build /tmp/build/source /
COPY --from=build  /tmp/dependencies/ /

CMD ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"]