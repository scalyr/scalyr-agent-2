{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py deb
# change version and build new package for agent upgrade test.
RUN echo "$(cat /agent_source/VERSION).1" > /agent_source/VERSION
WORKDIR /second_package
RUN python /agent_source/build_package.py deb

FROM ubuntu:14.04

RUN apt-get update -y

RUN apt-get install -y apt-utils build-essential
RUN apt-get install -y python python-pip python-dev

COPY agent_source/dev-requirements.txt dev-requirements.txt

# Upgrade pip so it supports Python version markers we use in our requirements file
RUN python2 -m pip install --upgrade --force-reinstall "pip==9.0.3"

RUN python2 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_build /second_package/scalyr-agent*.deb /scalyr-agent-second.deb
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
