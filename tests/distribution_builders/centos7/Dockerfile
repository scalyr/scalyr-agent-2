{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py rpm
# change version and build new package for agent upgrade test.
RUN echo "$(cat /agent_source/VERSION).1" > /agent_source/VERSION
WORKDIR /second_package
RUN python /agent_source/build_package.py rpm

FROM centos:7

# Needed for python-pip package
RUN yum update -y
RUN yum install -y epel-release

RUN yum update -y
RUN yum install -y initscripts python2 python3 gcc
RUN yum install -y python2-devel python2-pip python3-devel python3-pip

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_build /second_package/scalyr-agent*.rpm /scalyr-agent-second.rpm
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
