{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py deb
FROM ubuntu:18.04
RUN apt update -y

RUN apt install -y python build-essential

RUN apt install -y build-essential python python3
RUN apt install -y python-pip python-dev python3-pip python3-dev

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_build /agent_source /agent_source