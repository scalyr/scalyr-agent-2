{fpm_package_builder_dockerfile_deb}

FROM ubuntu:14.04

RUN apt-get update -y

RUN apt-get install -y apt-utils build-essential
RUN apt-get install -y software-properties-common python-software-properties

RUN add-apt-repository ppa:deadsnakes/ppa

RUN apt-get update -y

RUN apt-get install -y python python-pip python-dev
RUN apt-get install -y python3.5 python3.5-dev python3-pip

RUN rm /usr/bin/python3
RUN ln -s /usr/bin/python3.5 /usr/bin/python3

# Upgrade pip so it supports Python version markers we use in our requirements file
RUN python2 -m pip install --upgrade --force-reinstall "pip==9.0.3"
RUN python3 -m pip install --upgrade --force-reinstall "pip==9.0.3"

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_build /second_package/scalyr-agent*.deb /scalyr-agent-second.deb
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
