FROM package_builder_base

ADD . /agent_source

WORKDIR /packages

RUN python /agent_source/build_package.py rpm

RUN mv scalyr-agent-*.rpm scalyr-agent.rpm

