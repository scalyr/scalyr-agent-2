{fpm_package_builder_dockerfile_deb}

FROM ubuntu:18.04
RUN apt update
RUN apt install -y apt-utils build-essential

RUN apt install -y build-essential python python-pip python-dev

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_build /second_package/scalyr-agent*.deb /scalyr-agent-second.deb
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
